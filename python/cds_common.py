"""Constantes y construcción de peticiones al CDS, compartidas por los scripts.

No importa xarray ni boto3 a propósito, para que la imagen de ingesta sea pequeña.
"""
from __future__ import annotations

from datetime import date

DATASET = "reanalysis-era5-land-monthly-means"

# Caja que cubre el archipiélago canario: [Norte, Oeste, Sur, Este]
CANARIAS_AREA = [29.5, -18.5, 27.5, -13.2]


def months_available(year: int, today: date | None = None) -> list[int]:
    """Meses completos que se pueden pedir de un año.

    Criterio conservador: del año en curso solo los meses ya terminados. El último
    mes completo puede tardar unos días en publicarse, así que no se pide el mes actual.
    """
    today = today or date.today()
    if year < today.year:
        return list(range(1, 13))
    if year == today.year:
        return list(range(1, today.month))
    return []


def target_year(today: date | None = None) -> int:
    """Año que debe refrescar la ingesta periódica."""
    today = today or date.today()
    return today.year if today.month > 1 else today.year - 1


def split_blocks(start: int, end: int, block: int, today: date | None = None) -> list[tuple[int, int]]:
    """Divide [start, end] en bloques de `block` años; el año en curso va siempre solo,
    porque tiene menos meses disponibles que los demás y no se puede mezclar en una petición."""
    today = today or date.today()
    blocks: list[tuple[int, int]] = []
    past_end = min(end, today.year - 1)
    y = start
    while y <= past_end:
        y1 = min(y + block - 1, past_end)
        blocks.append((y, y1))
        y = y1 + 1
    if start <= today.year <= end and today.month > 1:
        blocks.append((today.year, today.year))
    return blocks


def build_request(start: int, end: int, today: date | None = None) -> dict:
    years = list(range(start, end + 1))
    month_sets = {tuple(months_available(y, today)) for y in years}
    if len(month_sets) != 1:
        raise ValueError("No se pueden mezclar años con distintos meses disponibles en una petición")
    months = month_sets.pop()
    if not months:
        raise ValueError(f"No hay meses completos disponibles para {start}-{end}")
    return {
        "variable": ["2m_temperature"],
        "product_type": "monthly_averaged_reanalysis",
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in months],
        "time": "00:00",
        "area": CANARIAS_AREA,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
