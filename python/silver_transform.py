"""Capa silver: valida los NetCDF de bronze y los unifica en un único cubo Zarr.

Flujo:
  1. Lista los NetCDF de s3://<bronze>/era5land/t2m_monthly/
  2. Pasa cada uno por el validador Java (puerta de calidad). Si alguno falla, se
     aborta sin escribir nada en silver (use --skip-invalid para omitirlos).
  3. Estandariza (dimensiones time/latitude/longitude, kelvin -> °C), une los bloques,
     elimina duplicados y comprueba que la serie mensual no tiene huecos.
  4. Escribe s3://<silver>/era5land/t2m_monthly.zarr

Variables de entorno: S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY y, opcionalmente,
S3_BUCKET_BRONZE (bronze), S3_BUCKET_SILVER (silver) y VALIDATOR_CMD
(por defecto "java -jar /app/nc-validator.jar").
"""
from __future__ import annotations

import argparse
import logging
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import xarray as xr

from s3_util import delete_keys, ensure_bucket, list_keys, s3_client

BRONZE_PREFIX = "era5land/t2m_monthly/"
SILVER_KEY = "era5land/t2m_monthly.zarr"
TIME_CHUNK = 120  # meses por chunk (10 años)

log = logging.getLogger("silver")


def validate(path: Path) -> bool:
    """Ejecuta el validador Java. Código de salida 0 = válido."""
    cmd = shlex.split(os.environ.get("VALIDATOR_CMD", "java -jar /app/nc-validator.jar")) + [str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for line in res.stdout.splitlines():
        log.info("  [validador] %s", line)
    if res.returncode != 0:
        log.error("  [validador] código de salida %d. stderr: %s", res.returncode, res.stderr.strip()[-500:])
        return False
    return True


def standardize(path: Path) -> xr.Dataset:
    """Un NetCDF de ERA5-Land -> Dataset con t2m en °C y dimensiones time/latitude/longitude."""
    ds = xr.open_dataset(path)
    try:
        if "valid_time" in ds.dims:
            ds = ds.rename({"valid_time": "time"})
        if "lat" in ds.dims:
            ds = ds.rename({"lat": "latitude"})
        if "lon" in ds.dims:
            ds = ds.rename({"lon": "longitude"})

        t2m = ds["t2m"]
        if "expver" in t2m.dims:  # algunas descargas mezclan versiones de experimento
            t2m = t2m.mean("expver", skipna=True)
        t2m = t2m.drop_vars([c for c in ("number", "expver") if c in t2m.coords])
        t2m = (t2m - 273.15).astype("float32")
        t2m.attrs = {
            "long_name": "2 metre temperature",
            "standard_name": "air_temperature",
            "units": "degC",
            "source_units": "K",
        }
        return t2m.to_dataset(name="t2m").load()
    finally:
        ds.close()


def merge(parts: list[xr.Dataset]) -> xr.Dataset:
    # join="exact": si las rejillas de dos bloques no coinciden, falla en vez de rellenar con NaN
    merged = xr.concat(parts, dim="time", join="exact").sortby("time")
    index = merged.get_index("time")
    dup = index.duplicated(keep="last")
    if dup.any():
        log.warning("%d meses duplicados entre bloques; se conserva el más reciente", int(dup.sum()))
        merged = merged.isel(time=~dup)
    return merged


def check_continuity(ds: xr.Dataset) -> None:
    index = ds.get_index("time")
    expected = pd.date_range(index[0], index[-1], freq="MS")
    missing = expected.difference(index)
    if len(missing) > 0:
        raise ValueError(
            f"La serie temporal tiene {len(missing)} meses sin datos, por ejemplo: "
            + ", ".join(str(m.date()) for m in missing[:5])
        )


def write_zarr(ds: xr.Dataset, local_dir: Path) -> Path:
    ds.attrs.update(
        title="ERA5-Land monthly mean 2m temperature, Canary Islands",
        source="Copernicus Climate Change Service (C3S), ERA5-Land monthly averaged data",
        license="Contains modified Copernicus Climate Change Service information",
        conventions="CF-1.8",
        processing="climate-canarias silver_transform: K to degC, merged and validated",
    )
    dims = ds["t2m"].dims
    chunks = tuple(min(TIME_CHUNK, ds.sizes[d]) if d == "time" else ds.sizes[d] for d in dims)
    target = local_dir / "t2m_monthly.zarr"
    # Formato Zarr v2: es el que leen más herramientas (xarray, netcdf-java, visores...)
    ds.to_zarr(target, mode="w", zarr_format=2, consolidated=True, encoding={"t2m": {"chunks": chunks}})
    return target


def upload_zarr(s3, bucket: str, local: Path) -> None:
    files = [p for p in local.rglob("*") if p.is_file()]
    # los metadatos (.zmetadata, .zarray, ...) van los últimos, para que nadie vea un cubo a medias
    files.sort(key=lambda p: p.name.startswith(".z"))
    new_keys = set()
    for p in files:
        key = f"{SILVER_KEY}/{p.relative_to(local).as_posix()}"
        s3.upload_file(str(p), bucket, key)
        new_keys.add(key)
    stale = [k for k in list_keys(s3, bucket, SILVER_KEY + "/") if k not in new_keys]
    if stale:
        delete_keys(s3, bucket, stale)
        log.info("Eliminados %d objetos obsoletos de la versión anterior", len(stale))
    log.info("Subido s3://%s/%s (%d objetos)", bucket, SILVER_KEY, len(new_keys))


class SilverError(RuntimeError):
    """Fallo controlado de la capa silver (puerta de calidad, bronze vacío...)."""


def run(skip_invalid: bool = False) -> dict:
    """Valida y unifica bronze en silver. Devuelve estadísticas del cubo resultante.

    Lanza SilverError si no hay datos o algún fichero no pasa el validador
    (salvo skip_invalid), y ValueError si la serie temporal tiene huecos.
    """
    bronze = os.environ.get("S3_BUCKET_BRONZE", "bronze")
    silver = os.environ.get("S3_BUCKET_SILVER", "silver")

    s3 = s3_client()
    keys = [k for k in list_keys(s3, bronze, BRONZE_PREFIX) if k.endswith(".nc")]
    if not keys:
        raise SilverError(f"No hay NetCDF en s3://{bronze}/{BRONZE_PREFIX}")
    log.info("%d ficheros en bronze", len(keys))

    parts: list[xr.Dataset] = []
    invalid: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for key in keys:
            local = Path(tmp) / Path(key).name
            s3.download_file(bronze, key, str(local))
            log.info("Validando s3://%s/%s", bronze, key)
            if not validate(local):
                invalid.append(key)
                continue
            parts.append(standardize(local))
            local.unlink()

        if invalid and not skip_invalid:
            raise SilverError("Ficheros inválidos, no se escribe silver: " + ", ".join(invalid))
        if not parts:
            raise SilverError("Ningún fichero válido")

        ds = merge(parts)
        check_continuity(ds)
        index = ds.get_index("time")
        log.info("Cubo unificado: %s -> %s (%d meses)", index[0].date(), index[-1].date(), len(index))

        ensure_bucket(s3, silver)
        upload_zarr(s3, silver, write_zarr(ds, Path(tmp)))

    log.info("Silver completada")
    return {
        "files": len(keys),
        "invalid_files": invalid,
        "months": len(index),
        "first_month": str(index[0].date()),
        "last_month": str(index[-1].date()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-invalid", action="store_true", help="omite los ficheros que no pasen el validador en vez de abortar")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(args.skip_invalid)
    except SilverError as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
