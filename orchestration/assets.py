"""Assets de Dagster de la plataforma: bronze -> silver -> gold.

Los assets son una capa fina de orquestación: la lógica vive en los módulos de python/
(ingest_bronze, silver_transform, gold_indicators), los mismos que usan los Jobs sueltos
de Kubernetes. Dagster aporta el grafo de dependencias, los checks de calidad, el
historial de ejecuciones y la programación.

Los datos no viajan entre assets: cada capa lee y escribe en MinIO. Por eso las
dependencias se declaran con `deps=` y no con argumentos.
"""
import io
import os
import tempfile
from pathlib import Path
from typing import Optional

import dagster as dg
import pandas as pd

import gold_indicators
import ingest_bronze
import silver_transform
from s3_util import list_keys, s3_client

GROUP = "clima_canarias"


class BronzeConfig(dg.Config):
    """Parámetros de la ingesta. Sin nada, refresca el año en curso."""

    start: Optional[int] = None
    end: Optional[int] = None
    force: Optional[bool] = None  # por defecto: sobrescribir solo si se refresca el año en curso


@dg.asset(
    group_name=GROUP,
    kinds={"python", "s3"},
    description="NetCDF de ERA5-Land (temperatura a 2 m, medias mensuales, Canarias) descargados del Copernicus CDS.",
)
def bronze_era5land(config: BronzeConfig) -> dg.MaterializeResult:
    force = config.force if config.force is not None else config.start is None
    uploaded = ingest_bronze.run(start=config.start, end=config.end, force=force)
    return dg.MaterializeResult(
        metadata={
            "objetos_subidos": len(uploaded),
            "claves": dg.MetadataValue.json(uploaded),
        }
    )


@dg.asset_check(
    asset=bronze_era5land,
    blocking=True,
    description="Pasa cada NetCDF de bronze por el validador Java (netcdf-java). Si falla, no se ejecuta silver.",
)
def bronze_java_validator() -> dg.AssetCheckResult:
    bucket = os.environ.get("S3_BUCKET", "bronze")
    s3 = s3_client()
    keys = [k for k in list_keys(s3, bucket, ingest_bronze.PREFIX + "/") if k.endswith(".nc")]
    failed: list = []
    with tempfile.TemporaryDirectory() as tmp:
        for key in keys:
            local = Path(tmp) / Path(key).name
            s3.download_file(bucket, key, str(local))
            if not silver_transform.validate(local):
                failed.append(key)
            local.unlink()
    return dg.AssetCheckResult(
        passed=bool(keys) and not failed,
        metadata={"ficheros_validados": len(keys), "ficheros_fallidos": dg.MetadataValue.json(failed)},
    )


@dg.asset(
    deps=[bronze_era5land],
    group_name=GROUP,
    kinds={"java", "python", "zarr"},
    description="Cubo Zarr unificado (tiempo x latitud x longitud) en °C, validado y sin huecos temporales.",
)
def silver_cube() -> dg.MaterializeResult:
    stats = silver_transform.run()
    return dg.MaterializeResult(
        metadata={
            "ficheros_bronze": stats["files"],
            "meses": stats["months"],
            "primer_mes": stats["first_month"],
            "ultimo_mes": stats["last_month"],
        }
    )


@dg.asset(
    name="gold_indicators",
    deps=[silver_cube],
    group_name=GROUP,
    kinds={"python", "parquet"},
    description="Anomalías respecto a 1991-2020, tendencias y rejillas por década, en Parquet.",
)
def gold_indicators_asset() -> dg.MaterializeResult:
    result = gold_indicators.run()
    return dg.MaterializeResult(
        metadata={
            "tendencia_c_por_decada": dg.MetadataValue.float(float(result["trend_c_per_decade"])),
            "calentamiento_total_c": dg.MetadataValue.float(float(result["total_warming_c"])),
            "anomalia_primeros_10_anios_c": dg.MetadataValue.float(float(result["anomaly_first_10y_c"])),
            "anomalia_ultimos_10_anios_c": dg.MetadataValue.float(float(result["anomaly_last_10y_c"])),
            "periodo": f"{result['period_start']}-{result['period_end']}",
            "anios_incompletos_excluidos": dg.MetadataValue.json(result["partial_years"]),
        }
    )


@dg.asset_check(
    asset=gold_indicators_asset,
    description="Red de seguridad: la tendencia debe estar entre 0 y 0,6 °C/década. Un valor fuera de ese rango indica un fallo en los datos o en el cálculo, no un resultado científico.",
)
def gold_trend_is_plausible() -> dg.AssetCheckResult:
    bucket = os.environ.get("S3_BUCKET_GOLD", "gold")
    body = s3_client().get_object(
        Bucket=bucket, Key=f"{gold_indicators.GOLD_PREFIX}/trend_summary.parquet"
    )["Body"].read()
    slope = float(pd.read_parquet(io.BytesIO(body)).iloc[0]["trend_c_per_decade"])
    return dg.AssetCheckResult(
        passed=0.0 < slope < 0.6,
        metadata={"tendencia_c_por_decada": dg.MetadataValue.float(slope)},
    )
