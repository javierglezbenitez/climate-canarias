"""Utilidades de acceso a S3/MinIO compartidas por los jobs de la plataforma."""
from __future__ import annotations

import logging
import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

NOT_FOUND = {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}

log = logging.getLogger("s3")


def s3_client():
    """Cliente S3 configurado desde S3_ENDPOINT, S3_ACCESS_KEY y S3_SECRET_KEY."""
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


def list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    return sorted(keys)


def delete_keys(s3, bucket: str, keys: list[str]) -> None:
    for i in range(0, len(keys), 1000):
        batch = keys[i : i + 1000]
        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True})
