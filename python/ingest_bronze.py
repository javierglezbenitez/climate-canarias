"""Ingesta ERA5-Land -> capa bronze (S3/MinIO).

Pensado para ejecutarse como Job/CronJob de Kubernetes. Toda la configuración llega
por variables de entorno (inyectadas desde Secrets), nunca en el código:

  CDSAPI_URL, CDSAPI_KEY                    credenciales del Climate Data Store
  S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY acceso al almacenamiento
  S3_BUCKET                                 (opcional, por defecto "bronze")

Idempotente: si el objeto ya existe en el bucket, se omite (salvo --force).
Sin argumentos refresca el año en curso, que es lo que necesita el CronJob mensual.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import boto3
import cdsapi
from botocore.client import Config
from botocore.exceptions import ClientError

from cds_common import DATASET, build_request, split_blocks, target_year

PREFIX = "era5land/t2m_monthly"
NOT_FOUND = {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}

log = logging.getLogger("ingest")


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] in NOT_FOUND:
            log.warning("El bucket %s no existe, se crea", bucket)
            s3.create_bucket(Bucket=bucket)
        else:
            raise


def object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in NOT_FOUND:
            return False
        raise


def ingest_block(cds, s3, bucket: str, y0: int, y1: int, force: bool) -> None:
    key = f"{PREFIX}/{y0}_{y1}.nc"
    if not force and object_exists(s3, bucket, key):
        log.info("s3://%s/%s ya existe, se omite", bucket, key)
        return

    request = build_request(y0, y1)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / f"{y0}_{y1}.nc"
        log.info("Solicitando %d-%d al CDS (meses %s)...", y0, y1, ",".join(request["month"]))
        cds.retrieve(DATASET, request, str(local))
        size = local.stat().st_size
        if size == 0:
            raise RuntimeError(f"El CDS devolvió un fichero vacío para {y0}-{y1}")
        s3.upload_file(
            str(local),
            bucket,
            key,
            ExtraArgs={"Metadata": {"source": "cds-era5land-monthly", "years": f"{y0}-{y1}"}},
        )
    log.info("Subido s3://%s/%s (%d bytes)", bucket, key, size)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=int, help="año inicial (por defecto, el año a refrescar)")
    parser.add_argument("--end", type=int, help="año final (por defecto, el año a refrescar)")
    parser.add_argument("--block", type=int, default=25, help="años por petición")
    parser.add_argument("--force", action="store_true", help="sobrescribe objetos existentes")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    default_year = target_year()
    start = args.start if args.start is not None else default_year
    end = args.end if args.end is not None else (default_year if args.start is None else date.today().year)

    blocks = split_blocks(start, end, args.block)
    if not blocks:
        log.error("No hay nada que ingerir para %d-%d", start, end)
        return 1

    bucket = os.environ.get("S3_BUCKET", "bronze")
    s3 = s3_client()
    ensure_bucket(s3, bucket)
    cds = cdsapi.Client()

    for y0, y1 in blocks:
        ingest_block(cds, s3, bucket, y0, y1, args.force)
    log.info("Ingesta completada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
