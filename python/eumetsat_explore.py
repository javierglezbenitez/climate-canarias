"""Exploración de colecciones de temperatura de superficie (LST) en el EUMETSAT Data Store.

Solo lista metadatos (no descarga nada). Sirve para decidir qué producto usar.

Uso (PowerShell):
    pip install eumdac
    $env:EUM_USER='tu_usuario_eumetsat'
    $env:EUM_PASSWORD='tu_contraseña'
    python python/eumetsat_explore.py
"""
from __future__ import annotations

import datetime as dt
import itertools
import os
import sys

import eumdac

# (colección, ventana de búsqueda de ejemplo)
CANDIDATES = [
    ("EO:EUM:DAT:0088", dt.datetime(2012, 7, 15, 11), dt.datetime(2012, 7, 15, 14)),  # MSG LST, registro histórico
    ("EO:EUM:DAT:0394", dt.datetime(2012, 7, 15, 11), dt.datetime(2012, 7, 15, 14)),  # MSG LST con efectos direccionales
    ("EO:EUM:DAT:1088", dt.datetime(2026, 11, 10, 11), dt.datetime(2026, 11, 10, 14)),  # MTG LST, reciente
]


def make_store() -> eumdac.DataStore | None:
    """Método nuevo (v2): usuario y contraseña de tu cuenta EUMETSAT.
    Si no están definidos, prueba el método antiguo (clave y secreto del consumidor)."""
    user = os.environ.get("EUM_USER", "").strip()
    pw = os.environ.get("EUM_PASSWORD", "")
    if user and pw:
        from eumdac.auth import Creds
        from eumdac.token import OAuth2Token

        print(f"Método nuevo (usuario y contraseña) con el usuario '{user}'")
        return eumdac.DataStore(OAuth2Token().set_credentials(Creds(user=user, pw=pw)))
    key = os.environ.get("EUM_KEY", "").strip()
    secret = os.environ.get("EUM_SECRET", "").strip()
    if key and secret:
        print("Método antiguo (clave y secreto del consumidor)")
        return eumdac.DataStore(eumdac.AccessToken((key, secret)))
    return None


def main() -> int:
    store = make_store()
    if store is None:
        print("Define EUM_USER y EUM_PASSWORD (tu usuario y contraseña de EUMETSAT)", file=sys.stderr)
        return 1

    for cid, start, end in CANDIDATES:
        print("=" * 78)
        print(cid)
        try:
            col = store.get_collection(cid)
            print("Título:", col.title)
            print("Opciones de búsqueda:", sorted(col.search_options))
            results = col.search(dtstart=start, dtend=end)
            print(f"Productos entre {start} y {end}: {results.total_results}")
            for p in itertools.islice(results, 4):
                print(f"  - {p}  sensing={p.sensing_start}  tamaño={p.size} KB")
                try:
                    print("    ficheros:", list(p.entries)[:6])
                except Exception as e:  # noqa: BLE001
                    print("    (no se pudieron listar los ficheros)", e)
        except Exception as e:  # noqa: BLE001
            print("ERROR:", type(e).__name__, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
