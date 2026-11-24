"""Ingesta (bronze) de temperatura de superficie terrestre (LST) de Meteosat/SEVIRI.

Fuente: EUMETSAT Data Store, colección EO:EUM:DAT:0088 (LSA SAF, registro 2004-2015,
rejilla de 0,05 grados, una imagen cada 15 minutos, licencia CC BY 4.0).

Para cada año y cada día elegido descarga la imagen de una hora concreta (por defecto
13:00 UTC), recorta Canarias y guarda un NetCDF pequeño en
s3://bronze/eumetsat/msg_lst/AAAA/. Los ficheros originales (disco completo) NO se
conservan: según la licencia de EUMETSAT no se redistribuyen los datos originales.

Variables de entorno: EUM_USER, EUM_PASSWORD (cuenta de EUMETSAT) y, para S3,
S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY (y S3_BUCKET_BRONZE, por defecto "bronze").

Ejemplos:
    python ingest_eumetsat.py                      # 2004-2015, 10 días de julio, 13:00 UTC
    python ingest_eumetsat.py --years 2010-2010 --days 15 --local ../data/eumetsat_bronze
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import xarray as xr

COLLECTION = "EO:EUM:DAT:0088"
PREFIX = "eumetsat/msg_lst"
# Canarias (mismo recuadro que ERA5-Land, con un pequeño margen)
LAT_MIN, LAT_MAX = 27.5, 29.5
LON_MIN, LON_MAX = -18.5, -13.2
VARS = ["LST", "quality_flag", "standard_error"]
DEFAULT_DAYS = [1, 4, 7, 10, 13, 16, 19, 22, 25, 28]

log = logging.getLogger("ingest_eumetsat")


def scene_key(ts: dt.datetime) -> str:
    return f"{PREFIX}/{ts:%Y}/lst_canarias_{ts:%Y%m%dT%H%M}.nc"


def _slice(coord, lo: float, hi: float) -> slice:
    """Las latitudes de estos ficheros van de 80 a -80 (descendentes): el slice debe respetarlo."""
    return slice(hi, lo) if float(coord[0]) > float(coord[-1]) else slice(lo, hi)


def crop_to_canarias(src: Path, dest: Path) -> dict:
    """Recorta el fichero de disco completo a Canarias y lo guarda comprimido y en float32."""
    with xr.open_dataset(src) as ds:
        sub = ds[VARS].sel(lat=_slice(ds["lat"], LAT_MIN, LAT_MAX), lon=_slice(ds["lon"], LON_MIN, LON_MAX)).load()
        sub = sub.astype("float32")
        sub.attrs = {
            "title": "MSG SEVIRI Land Surface Temperature recortada a Canarias",
            "source": "EUMETSAT LSA SAF, colección EO:EUM:DAT:0088",
            "license": "CC BY 4.0 (EUMETSAT)",
            "platform": str(ds.attrs.get("platform", "")),
            "algorithm_version": str(ds.attrs.get("algorithm_version", "")),
        }
        for name in VARS:
            sub[name].encoding = {"zlib": True, "complevel": 4, "dtype": "float32"}
        n_valid = int(sub["LST"].notnull().sum())
        sub.to_netcdf(dest)
    return {"n_valid": n_valid, "shape": tuple(sub["LST"].shape)}


def find_product(store, ts: dt.datetime):
    col = store.get_collection(COLLECTION)
    res = col.search(dtstart=ts - dt.timedelta(minutes=2), dtend=ts + dt.timedelta(minutes=2))
    for product in res:
        return product
    return None


def download_nc(product, dest: Path) -> None:
    name = next(e for e in product.entries if e.endswith(".nc"))
    with product.open(entry=name) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)


def with_retries(fn, attempts: int = 3, pause: float = 5.0):
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts:
                raise
            log.warning("Intento %d/%d fallido (%s: %s); reintento", i, attempts, type(e).__name__, e)
            time.sleep(pause * i)


class LocalSink:
    def __init__(self, root: Path):
        self.root = root

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def put(self, key: str, path: Path) -> None:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)


class S3Sink:
    def __init__(self, bucket: str):
        from s3_util import ensure_bucket, s3_client

        self.s3, self.bucket = s3_client(), bucket
        ensure_bucket(self.s3, bucket)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def put(self, key: str, path: Path) -> None:
        self.s3.upload_file(str(path), self.bucket, key)


def run(store, sink, years: range, days: list[int], month: int = 7, hour: int = 13, force: bool = False) -> dict:
    done = skipped = missing = failed = 0
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        for year in years:
            for day in days:
                ts = dt.datetime(year, month, day, hour, 0)
                key = scene_key(ts)
                if not force and sink.exists(key):
                    skipped += 1
                    continue
                try:
                    product = with_retries(lambda: find_product(store, ts))
                    if product is None:
                        log.warning("%s: no hay imagen en el Data Store", ts)
                        missing += 1
                        continue
                    raw, small = tmp / "raw.nc", tmp / "small.nc"
                    with_retries(lambda: download_nc(product, raw))
                    info = crop_to_canarias(raw, small)
                    sink.put(key, small)
                    log.info("%s -> %s (%d píxeles válidos de %s)", ts, key, info["n_valid"], info["shape"])
                    done += 1
                except Exception as e:  # noqa: BLE001
                    log.error("%s: fallo %s: %s", ts, type(e).__name__, e)
                    failed += 1
                finally:
                    for f in ("raw.nc", "small.nc"):
                        (tmp / f).unlink(missing_ok=True)
    return {"descargadas": done, "ya_existian": skipped, "sin_dato": missing, "fallidas": failed}


def make_store():
    import eumdac
    from eumdac.auth import Creds
    from eumdac.token import OAuth2Token

    user, pw = os.environ.get("EUM_USER", "").strip(), os.environ.get("EUM_PASSWORD", "")
    if not user or not pw:
        raise SystemExit("Define EUM_USER y EUM_PASSWORD (tu cuenta de EUMETSAT)")
    return eumdac.DataStore(OAuth2Token().set_credentials(Creds(user=user, pw=pw)))


def parse_years(text: str) -> range:
    a, _, b = text.partition("-")
    return range(int(a), int(b or a) + 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2004-2015", help="rango, p. ej. 2004-2015 (el registro MSG llega hasta 2015)")
    ap.add_argument("--days", default=",".join(map(str, DEFAULT_DAYS)), help="días del mes separados por comas")
    ap.add_argument("--month", type=int, default=7)
    ap.add_argument("--hour", type=int, default=13, help="hora UTC")
    ap.add_argument("--local", help="carpeta local en vez de S3 (para pruebas)")
    ap.add_argument("--force", action="store_true", help="volver a descargar lo que ya existe")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sink = LocalSink(Path(args.local)) if args.local else S3Sink(os.environ.get("S3_BUCKET_BRONZE", "bronze"))
    days = [int(d) for d in args.days.split(",")]
    result = run(make_store(), sink, parse_years(args.years), days, args.month, args.hour, args.force)
    log.info("Resumen: %s", result)
    return 1 if result["fallidas"] else 0


if __name__ == "__main__":
    sys.exit(main())
