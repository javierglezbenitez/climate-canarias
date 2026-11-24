"""Descarga los Parquet de la capa gold (MinIO) a web/public/data para la demo web.

Uso (con el port-forward de MinIO abierto en 9000):
    $env:S3_ENDPOINT="http://localhost:9000"
    $env:S3_ACCESS_KEY="climateadmin"
    $env:S3_SECRET_KEY="<tu contraseña>"
    python python/export_gold.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from s3_util import list_keys, s3_client

PREFIXES = ["era5land/indicators/", "eumetsat/msg_lst/"]


def main() -> int:
    bucket = os.environ.get("S3_BUCKET_GOLD", "gold")
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "web" / "public" / "data"
    out.mkdir(parents=True, exist_ok=True)
    s3 = s3_client()
    keys = [k for pre in PREFIXES for k in list_keys(s3, bucket, pre) if k.endswith(".parquet")]
    if not keys:
        print(f"No hay Parquet en s3://{bucket}/. Ejecuta antes la capa gold.", file=sys.stderr)
        return 1
    for key in keys:
        dest = out / Path(key).name
        s3.download_file(bucket, key, str(dest))
        print(f"{key} -> {dest} ({dest.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
