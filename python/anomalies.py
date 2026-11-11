"""Calcula la anomalía anual de temperatura en Canarias respecto a 1991-2020
y dibuja los 'warming stripes'.

Método:
  1. Media espacial ponderada por cos(latitud) de t2m (ERA5-Land solo tiene tierra;
     el mar son NaN y se ignora).
  2. Climatología mensual de referencia: media de cada mes en 1991-2020
     (línea base estándar de la OMM).
  3. Anomalía mensual = valor - climatología de ese mes.
  4. Anomalía anual = media de las anomalías mensuales del año.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.colors import Normalize

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"

BASE_START, BASE_END = 1991, 2020


def load_t2m(path: Path) -> xr.DataArray:
    ds = xr.open_dataset(path)
    # El CDS nuevo usa 'valid_time'; el antiguo usaba 'time'.
    if "valid_time" in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    lat = "latitude" if "latitude" in ds.dims else "lat"
    lon = "longitude" if "longitude" in ds.dims else "lon"
    t2m = ds["t2m"]
    # Algunas descargas incluyen la dimensión 'expver'; nos quedamos con el dato válido.
    if "expver" in t2m.dims:
        t2m = t2m.mean("expver", skipna=True)
    t2m = t2m - 273.15  # K -> °C
    t2m.attrs["units"] = "degC"
    return t2m.rename({lat: "lat", lon: "lon"})


def spatial_mean(t2m: xr.DataArray) -> xr.DataArray:
    weights = np.cos(np.deg2rad(t2m["lat"]))
    return t2m.weighted(weights).mean(dim=["lat", "lon"], skipna=True)


def monthly_anomaly(series: xr.DataArray) -> xr.DataArray:
    base = series.sel(time=slice(f"{BASE_START}-01-01", f"{BASE_END}-12-31"))
    if base.time.size == 0:
        raise ValueError(
            f"El fichero no cubre el periodo base {BASE_START}-{BASE_END}; "
            "descarga un rango que lo incluya."
        )
    climatology = base.groupby("time.month").mean("time")
    return series.groupby("time.month") - climatology


def annual_table(anom: xr.DataArray, series: xr.DataArray) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "temp_media_c": series.to_series().groupby(series["time"].dt.year.values).mean(),
            "anomalia_c": anom.to_series().groupby(anom["time"].dt.year.values).mean(),
        }
    )
    df.index.name = "year"
    return df.round(3)


def plot_stripes(df: pd.DataFrame, out: Path) -> None:
    vals = df["anomalia_c"].to_numpy()
    lim = float(np.nanmax(np.abs(vals)))
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.imshow(
        vals[np.newaxis, :],
        aspect="auto",
        cmap="RdBu_r",
        norm=Normalize(vmin=-lim, vmax=lim),
        extent=[df.index.min(), df.index.max() + 1, 0, 1],
    )
    ax.set_yticks([])
    ax.set_title(
        f"Canarias: anomalía anual de temperatura (base {BASE_START}-{BASE_END})\n"
        f"{df.index.min()}-{df.index.max()} · Fuente: ERA5-Land, Copernicus C3S",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", help="NetCDF de entrada (por defecto, el más reciente en data/raw)")
    args = parser.parse_args()

    path = Path(args.file) if args.file else max(RAW_DIR.glob("era5land_t2m_monthly_*.nc"), key=lambda p: p.stat().st_mtime, default=None)
    if path is None or not path.exists():
        print("No hay NetCDF en data/raw. Ejecuta antes download_era5land.py", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t2m = load_t2m(path)
    series = spatial_mean(t2m)
    anom = monthly_anomaly(series)
    df = annual_table(anom, series)

    csv = OUT_DIR / "annual_anomaly_canarias.csv"
    png = OUT_DIR / "warming_stripes_canarias.png"
    df.to_csv(csv)
    plot_stripes(df, png)

    recent = df.tail(10)["anomalia_c"].mean()
    early = df.head(10)["anomalia_c"].mean()
    print(f"Años: {df.index.min()}-{df.index.max()}")
    print(f"Anomalía media primeros 10 años: {early:+.2f} °C")
    print(f"Anomalía media últimos 10 años:  {recent:+.2f} °C")
    print(f"Guardado: {csv}\nGuardado: {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
