"""Silver y gold de la temperatura de superficie (LST) de MSG para Canarias.

bronze  s3://bronze/eumetsat/msg_lst/AAAA/*.nc   imágenes recortadas (ingest_eumetsat.py)
silver  s3://silver/eumetsat/msg_lst_canarias.zarr   cubo (tiempo, lat, lon) con todas las imágenes
gold    s3://gold/eumetsat/msg_lst/lst_summer_grid.parquet     media de verano por celda de 0,05 grados
        s3://gold/eumetsat/msg_lst/lst_summer_yearly.parquet   media por año (variabilidad entre veranos)

Filtro de calidad: se descartan píxeles fuera del rango válido del producto (-80 a 70 °C) y los
que tienen un error estimado superior a 3 K. El producto solo da temperatura con cielo despejado,
así que las medias son "de cielo despejado". La bandera quality_flag se conserva en silver pero
no se usa para filtrar, porque su significado por bits no se ha verificado todavía.

Variables de entorno: S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, y opcionalmente
S3_BUCKET_BRONZE / S3_BUCKET_SILVER / S3_BUCKET_GOLD.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from s3_util import delete_keys, ensure_bucket, list_keys, s3_client

BRONZE_PREFIX = "eumetsat/msg_lst/"
SILVER_KEY = "eumetsat/msg_lst_canarias.zarr"
GOLD_PREFIX = "eumetsat/msg_lst"
LST_MIN, LST_MAX = -80.0, 70.0
MAX_ERROR_K = 3.0
MIN_VALID_FRACTION = 0.25  # una celda necesita datos válidos en al menos el 25 % de las imágenes

log = logging.getLogger("lst_summer")


class LstError(RuntimeError):
    pass


def load_bronze(s3, bucket: str, root: Path) -> xr.Dataset:
    keys = [k for k in list_keys(s3, bucket, BRONZE_PREFIX) if k.endswith(".nc")]
    if not keys:
        raise LstError(f"No hay imágenes en s3://{bucket}/{BRONZE_PREFIX}. Ejecuta antes ingest_eumetsat.py")
    parts = []
    for key in keys:
        local = root / key
        local.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(local))
        with xr.open_dataset(local) as ds:
            parts.append(ds.load())
    log.info("Leídas %d imágenes de bronze", len(parts))
    try:
        cube = xr.concat(parts, dim="time", join="exact").sortby("time")
    except ValueError as e:
        raise LstError(f"Las imágenes no comparten la misma rejilla: {e}") from e
    return cube


def to_silver(cube: xr.Dataset, local_dir: Path) -> Path:
    cube = cube.copy()
    cube.attrs = {
        "title": "MSG SEVIRI Land Surface Temperature, Canarias, imágenes de verano",
        "source": "EUMETSAT LSA SAF, colección EO:EUM:DAT:0088",
        "license": "CC BY 4.0 (EUMETSAT)",
        "processing": "climate-canarias: recorte y apilado",
    }
    target = local_dir / "msg_lst_canarias.zarr"
    chunks = {v: (min(16, cube.sizes["time"]), cube.sizes["lat"], cube.sizes["lon"]) for v in cube.data_vars}
    cube.to_zarr(target, mode="w", zarr_format=2, consolidated=True, encoding={v: {"chunks": c} for v, c in chunks.items()})
    return target


def upload_zarr(s3, bucket: str, local: Path) -> None:
    files = sorted((p for p in local.rglob("*") if p.is_file()), key=lambda p: p.name.startswith(".z"))
    new = set()
    for p in files:
        key = f"{SILVER_KEY}/{p.relative_to(local).as_posix()}"
        s3.upload_file(str(p), bucket, key)
        new.add(key)
    stale = [k for k in list_keys(s3, bucket, SILVER_KEY + "/") if k not in new]
    if stale:
        delete_keys(s3, bucket, stale)
    log.info("Subido s3://%s/%s (%d objetos)", bucket, SILVER_KEY, len(new))


def valid_lst(cube: xr.Dataset) -> xr.DataArray:
    lst = cube["LST"]
    ok = lst.notnull() & (lst > LST_MIN) & (lst < LST_MAX) & (cube["standard_error"] <= MAX_ERROR_K)
    return lst.where(ok)


def gold_tables(cube: xr.Dataset) -> tuple[pd.DataFrame, pd.DataFrame]:
    lst = valid_lst(cube)
    n_total = cube.sizes["time"]
    n_obs = lst.notnull().sum("time")
    keep = n_obs >= max(1, int(np.ceil(MIN_VALID_FRACTION * n_total)))

    grid = xr.Dataset(
        {
            "lst_mean_c": lst.mean("time").where(keep),
            "lst_max_c": lst.max("time").where(keep),
            "n_obs": n_obs.where(keep),
        }
    ).to_dataframe().reset_index().dropna(subset=["lst_mean_c"])
    grid = grid.rename(columns={"lat": "latitude", "lon": "longitude"}).astype({"latitude": "float64", "longitude": "float64"})
    grid["n_total"] = n_total
    grid["n_obs"] = grid["n_obs"].astype(int)
    grid = grid[["latitude", "longitude", "lst_mean_c", "lst_max_c", "n_obs", "n_total"]].round(
        {"latitude": 2, "longitude": 2, "lst_mean_c": 2, "lst_max_c": 2}
    )
    if grid.empty:
        raise LstError("Ninguna celda cumple el mínimo de datos válidos; revisa el filtro de calidad")

    # Media por año sobre las mismas celdas siempre (si no, la nubosidad cambiaría la zona medida)
    stable = lst.where(keep)
    per_scene = stable.mean(["lat", "lon"])
    years = pd.DatetimeIndex(cube["time"].values).year
    yearly = (
        pd.DataFrame({"year": years, "lst_mean_c": per_scene.values, "valid_cells": stable.notnull().sum(["lat", "lon"]).values})
        .dropna(subset=["lst_mean_c"])
        .groupby("year")
        .agg(lst_mean_c=("lst_mean_c", "mean"), n_scenes=("lst_mean_c", "count"), mean_valid_cells=("valid_cells", "mean"))
        .reset_index()
        .round({"lst_mean_c": 2, "mean_valid_cells": 1})
    )
    return grid, yearly


def run() -> dict:
    s3 = s3_client()
    bronze = os.environ.get("S3_BUCKET_BRONZE", "bronze")
    silver = os.environ.get("S3_BUCKET_SILVER", "silver")
    gold = os.environ.get("S3_BUCKET_GOLD", "gold")
    for b in (silver, gold):
        ensure_bucket(s3, b)
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        cube = load_bronze(s3, bronze, tmp / "bronze")
        upload_zarr(s3, silver, to_silver(cube, tmp / "silver"))
        grid, yearly = gold_tables(cube)
        for name, df in (("lst_summer_grid.parquet", grid), ("lst_summer_yearly.parquet", yearly)):
            local = tmp / name
            df.to_parquet(local, index=False, compression="snappy")
            s3.upload_file(str(local), gold, f"{GOLD_PREFIX}/{name}")
            log.info("Subido s3://%s/%s/%s (%d filas)", gold, GOLD_PREFIX, name, len(df))
    return {
        "imagenes": int(cube.sizes["time"]),
        "celdas": len(grid),
        "lst_media_c": round(float(grid["lst_mean_c"].mean()), 2),
        "lst_max_c": round(float(grid["lst_max_c"].max()), 2),
        "años": len(yearly),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        log.info("Resumen: %s", run())
    except LstError as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
