"""Capa gold: indicadores de cambio de temperatura a partir del cubo Zarr de silver.

Método (línea base de la OMM, 1991-2020):
  - Climatología mensual por celda = media de cada mes en 1991-2020.
  - Anomalía = valor - climatología de ese mes (así se elimina el ciclo estacional).
  - Media espacial ponderada por cos(latitud), ignorando las celdas de mar (sin datos).
  - Los años incompletos (p. ej. el año en curso) se marcan y NO entran en tendencias
    ni en medias por década, para no sesgar por la estacionalidad.

Salidas (Parquet) en s3://<gold>/era5land/indicators/:
  monthly_anomaly.parquet     serie mensual del archipiélago
  annual_anomaly.parquet      serie anual, con indicador de año completo
  trend_summary.parquet       tendencia lineal (°C/década) y comparación primeros/últimos 10 años
  decadal_anomaly_grid.parquet  anomalía media por década y celda (para el mapa con deslizador)
  trend_grid.parquet          tendencia (°C/década) por celda

Variables de entorno: S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY y, opcionalmente,
S3_BUCKET_SILVER (silver) y S3_BUCKET_GOLD (gold).
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

from s3_util import ensure_bucket, list_keys, s3_client

BASE_START, BASE_END = 1991, 2020
SILVER_KEY = "era5land/t2m_monthly.zarr"
GOLD_PREFIX = "era5land/indicators"

log = logging.getLogger("gold")


def download_zarr(s3, bucket: str, root: Path) -> Path:
    keys = list_keys(s3, bucket, SILVER_KEY + "/")
    if not keys:
        raise FileNotFoundError(f"No hay cubo en s3://{bucket}/{SILVER_KEY}. Ejecuta antes la capa silver.")
    for key in keys:
        dest = root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(dest))
    return root / SILVER_KEY


def load_t2m(path: Path) -> xr.DataArray:
    ds = xr.open_dataset(path, engine="zarr", chunks=None)
    try:
        t2m = ds["t2m"].load()
    finally:
        ds.close()
    t2m = t2m.assign_coords(latitude=t2m["latitude"].round(2), longitude=t2m["longitude"].round(2))
    return t2m


def monthly_anomaly(t2m: xr.DataArray) -> xr.DataArray:
    base = t2m.sel(time=slice(f"{BASE_START}-01-01", f"{BASE_END}-12-31"))
    if base.sizes["time"] != 12 * (BASE_END - BASE_START + 1):
        raise ValueError(
            f"El cubo no cubre completo el periodo base {BASE_START}-{BASE_END} "
            f"({base.sizes['time']} meses de {12 * (BASE_END - BASE_START + 1)})"
        )
    climatology = base.groupby("time.month").mean("time")
    anomaly = t2m.groupby("time.month") - climatology
    return anomaly.drop_vars("month", errors="ignore")


def area_mean(da: xr.DataArray) -> xr.DataArray:
    weights = np.cos(np.deg2rad(da["latitude"]))
    return da.weighted(weights).mean(dim=["latitude", "longitude"], skipna=True)


def monthly_table(t2m: xr.DataArray, anom: xr.DataArray) -> pd.DataFrame:
    time = pd.DatetimeIndex(t2m["time"].values)
    return pd.DataFrame(
        {
            "time": time,
            "year": time.year,
            "month": time.month,
            "temp_c": area_mean(t2m).values,
            "anomaly_c": area_mean(anom).values,
        }
    ).round({"temp_c": 3, "anomaly_c": 3})


def annual_table(monthly: pd.DataFrame) -> pd.DataFrame:
    annual = (
        monthly.groupby("year")
        .agg(n_months=("month", "count"), temp_mean_c=("temp_c", "mean"), anomaly_c=("anomaly_c", "mean"))
        .reset_index()
    )
    annual["complete"] = annual["n_months"] == 12
    return annual.round({"temp_mean_c": 3, "anomaly_c": 3})


def trend_summary(annual: pd.DataFrame) -> pd.DataFrame:
    full = annual[annual["complete"]]
    if len(full) < 20:
        raise ValueError("Se necesitan al menos 20 años completos para calcular una tendencia")
    years = full["year"].to_numpy(dtype=float)
    slope, _ = np.polyfit(years, full["anomaly_c"].to_numpy(), 1)
    first, last = int(years.min()), int(years.max())
    return pd.DataFrame(
        [
            {
                "period_start": first,
                "period_end": last,
                "n_years": len(full),
                "baseline": f"{BASE_START}-{BASE_END}",
                "trend_c_per_decade": round(float(slope) * 10, 4),
                "total_warming_c": round(float(slope) * (last - first), 3),
                "anomaly_first_10y_c": round(float(full.head(10)["anomaly_c"].mean()), 3),
                "anomaly_last_10y_c": round(float(full.tail(10)["anomaly_c"].mean()), 3),
            }
        ]
    )


def annual_grid(anom: xr.DataArray, complete_years: list[int]) -> xr.DataArray:
    annual = anom.groupby("time.year").mean("time")
    return annual.sel(year=complete_years)


def decadal_grid(annual: xr.DataArray) -> pd.DataFrame:
    years = annual["year"].values
    frames = []
    for decade in sorted(set(int(y) // 10 * 10 for y in years)):
        sel = annual.sel(year=[y for y in years if int(y) // 10 * 10 == decade])
        df = sel.mean("year").to_dataframe(name="anomaly_c").reset_index()
        df["decade"] = decade
        df["n_years"] = sel.sizes["year"]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True).dropna(subset=["anomaly_c"])
    return out[["decade", "n_years", "latitude", "longitude", "anomaly_c"]].round({"anomaly_c": 3})


def trend_grid(annual: xr.DataArray) -> pd.DataFrame:
    x = annual["year"].values.astype(float)
    xc = x - x.mean()
    y = annual.transpose("year", "latitude", "longitude").values
    slope = (xc[:, None, None] * (y - y.mean(axis=0))).sum(axis=0) / (xc**2).sum()
    da = xr.DataArray(
        slope * 10,
        coords={"latitude": annual["latitude"], "longitude": annual["longitude"]},
        dims=("latitude", "longitude"),
    )
    df = da.to_dataframe(name="trend_c_per_decade").reset_index().dropna()
    return df.round({"trend_c_per_decade": 4})


def upload_parquet(s3, bucket: str, name: str, df: pd.DataFrame, tmp: Path) -> None:
    local = tmp / name
    df.to_parquet(local, index=False, compression="snappy")
    key = f"{GOLD_PREFIX}/{name}"
    s3.upload_file(str(local), bucket, key)
    log.info("Subido s3://%s/%s (%d filas)", bucket, key, len(df))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    silver = os.environ.get("S3_BUCKET_SILVER", "silver")
    gold = os.environ.get("S3_BUCKET_GOLD", "gold")

    s3 = s3_client()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        t2m = load_t2m(download_zarr(s3, silver, tmp / "in"))
        log.info("Cubo cargado: %s", dict(t2m.sizes))

        anom = monthly_anomaly(t2m)
        monthly = monthly_table(t2m, anom)
        annual = annual_table(monthly)
        summary = trend_summary(annual)
        complete_years = annual.loc[annual["complete"], "year"].tolist()
        partial = annual.loc[~annual["complete"], "year"].tolist()
        if partial:
            log.info("Años incompletos (excluidos de tendencias y décadas): %s", partial)

        grid_annual = annual_grid(anom, complete_years)
        decades = decadal_grid(grid_annual)
        trends = trend_grid(grid_annual)

        row = summary.iloc[0]
        log.info(
            "Tendencia %d-%d: %+.3f °C/década (calentamiento total %+.2f °C). "
            "Anomalía primeros 10 años %+.2f °C, últimos 10 años %+.2f °C",
            row.period_start, row.period_end, row.trend_c_per_decade, row.total_warming_c,
            row.anomaly_first_10y_c, row.anomaly_last_10y_c,
        )

        ensure_bucket(s3, gold)
        out = tmp / "out"
        out.mkdir()
        for name, df in [
            ("monthly_anomaly.parquet", monthly),
            ("annual_anomaly.parquet", annual),
            ("trend_summary.parquet", summary),
            ("decadal_anomaly_grid.parquet", decades),
            ("trend_grid.parquet", trends),
        ]:
            upload_parquet(s3, gold, name, df, out)

    log.info("Gold completada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
