"""Sondeo del EUMETSAT Data Store para elegir producto de temperatura de superficie (LST).

1. Cobertura: para cada año busca las 13:00 UTC del 15 de julio en cada colección.
2. Descarga UN fichero MSG (~3 MB) a data/eumetsat_sample/ y muestra su estructura.

Uso (PowerShell, desde la raíz del proyecto):
    $env:EUM_USER='tu_usuario'
    $env:EUM_PASSWORD='tu_contraseña'
    python python/eumetsat_probe.py
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
from pathlib import Path

import eumdac
from eumdac.auth import Creds
from eumdac.token import OAuth2Token

COLLECTIONS = {
    "0088 MSG LST registro": "EO:EUM:DAT:0088",
    "0394 MSG LST direcc.": "EO:EUM:DAT:0394",
    "1088 MTG LST": "EO:EUM:DAT:1088",
}
OUT = Path("data/eumetsat_sample")


def main() -> int:
    user, pw = os.environ.get("EUM_USER", "").strip(), os.environ.get("EUM_PASSWORD", "")
    if not user or not pw:
        print("Define EUM_USER y EUM_PASSWORD", file=sys.stderr)
        return 1
    store = eumdac.DataStore(OAuth2Token().set_credentials(Creds(user=user, pw=pw)))

    print("\nCobertura: productos entre 12:55 y 13:05 UTC del 15 de julio de cada año")
    print(f"{'año':<6}" + "".join(f"{n:<26}" for n in COLLECTIONS))
    first_msg = None
    for year in range(2003, 2027):
        row = f"{year:<6}"
        for name, cid in COLLECTIONS.items():
            try:
                res = store.get_collection(cid).search(
                    dtstart=dt.datetime(year, 7, 15, 12, 55), dtend=dt.datetime(year, 7, 15, 13, 5)
                )
                n = res.total_results
                if cid.endswith("0088") and n and first_msg is None and year >= 2010:
                    first_msg = next(iter(res))
            except Exception as e:  # noqa: BLE001
                n = f"err {type(e).__name__}"
            row += f"{n!s:<26}"
        print(row)

    if first_msg is None:
        print("\nNo se encontró un fichero MSG para descargar de muestra.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    nc_name = next(e for e in first_msg.entries if e.endswith(".nc"))
    dest = OUT / nc_name
    print(f"\nDescargando {nc_name} -> {dest}")
    with first_msg.open(entry=nc_name) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)

    try:
        import xarray as xr

        ds = xr.open_dataset(dest)
        print("\n----- Estructura del fichero -----")
        print(ds)
        for v in ds.data_vars:
            print(f"\n{v}: dims={ds[v].dims} shape={ds[v].shape} attrs={dict(list(ds[v].attrs.items())[:6])}")
    except Exception as e:  # noqa: BLE001
        print("No se pudo abrir con xarray:", type(e).__name__, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
