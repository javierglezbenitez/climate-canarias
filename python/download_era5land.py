"""Descarga ERA5-Land (medias mensuales de temperatura a 2 m) para Canarias.

Requiere ~/.cdsapirc con tu clave del Climate Data Store y haber aceptado la
licencia del dataset en la web de Copernicus.

Diseño: idempotente. Si el fichero de salida ya existe, no se vuelve a descargar
(usa --force para obligarlo). Para rangos grandes se descarga por bloques de
años, de modo que un fallo a mitad no obliga a empezar desde cero.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cdsapi
import xarray as xr

DATASET = "reanalysis-era5-land-monthly-means"

# Caja que cubre el archipiélago canario: [Norte, Oeste, Sur, Este]
CANARIAS_AREA = [29.5, -18.5, 27.5, -13.2]

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

log = logging.getLogger("download")


def chunk_path(start: int, end: int) -> Path:
    return RAW_DIR / f"era5land_t2m_monthly_{start}_{end}.nc"


def download_chunk(client: cdsapi.Client, start: int, end: int, force: bool) -> Path:
    target = chunk_path(start, end)
    if target.exists() and not force:
        log.info("Ya existe %s, se omite", target.name)
        return target

    request = {
        "variable": ["2m_temperature"],
        "product_type": "monthly_averaged_reanalysis",
        "year": [str(y) for y in range(start, end + 1)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": "00:00",
        "area": CANARIAS_AREA,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    log.info("Solicitando %d-%d al CDS (puede tardar en cola)...", start, end)
    tmp = target.with_suffix(".part")
    client.retrieve(DATASET, request, str(tmp))
    tmp.rename(target)  # renombrado al final: nunca queda un fichero a medias
    log.info("Guardado %s", target.name)
    return target


def merge_chunks(paths: list[Path], start: int, end: int) -> Path:
    out = RAW_DIR / f"era5land_t2m_monthly_{start}_{end}.nc"
    if len(paths) == 1 and paths[0] == out:
        return out
    log.info("Uniendo %d bloques en %s", len(paths), out.name)
    datasets = [xr.open_dataset(p) for p in paths]
    time_dim = "valid_time" if "valid_time" in datasets[0].dims else "time"
    merged = xr.concat(datasets, dim=time_dim).sortby(time_dim)
    merged.to_netcdf(out)
    for ds in datasets:
        ds.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=1950)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--block", type=int, default=25, help="años por petición")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    client = cdsapi.Client()
    paths = []
    for y0 in range(args.start, args.end + 1, args.block):
        y1 = min(y0 + args.block - 1, args.end)
        paths.append(download_chunk(client, y0, y1, args.force))

    final = merge_chunks(paths, args.start, args.end)
    log.info("Listo: %s", final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
