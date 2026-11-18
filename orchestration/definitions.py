"""Punto de entrada de Dagster: `dagster api grpc -m orchestration.definitions`."""
import dagster as dg

from orchestration.assets import (
    bronze_era5land,
    bronze_java_validator,
    gold_indicators_asset,
    gold_trend_is_plausible,
    silver_cube,
)

pipeline_mensual = dg.define_asset_job(
    name="pipeline_mensual",
    selection=dg.AssetSelection.all(),
    description="bronze -> validación Java -> silver -> gold",
)

# Día 10 de cada mes a las 06:00 UTC: el CDS ya ha publicado el mes anterior.
programacion_mensual = dg.ScheduleDefinition(
    name="programacion_mensual",
    job=pipeline_mensual,
    cron_schedule="0 6 10 * *",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

defs = dg.Definitions(
    assets=[bronze_era5land, silver_cube, gold_indicators_asset],
    asset_checks=[bronze_java_validator, gold_trend_is_plausible],
    jobs=[pipeline_mensual],
    schedules=[programacion_mensual],
)
