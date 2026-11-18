# Clima en Canarias: tu vida en un planeta que se calienta

Plataforma de datos sobre el cambio de temperaturas en Canarias a partir de datos
de Copernicus (y, más adelante, EUMETSAT). Proyecto para practicar data engineering,
Kubernetes, Terraform y cloud, combinando **Python** y **Java**.

## Reparto de lenguajes

| Lenguaje | Papel en el proyecto |
|---|---|
| Python | Descarga (cdsapi), exploración y cálculo científico (xarray, pandas) |
| Java | Validación de ficheros NetCDF (netcdf-java) y, en fases posteriores, API con Spring Boot y consumidores de streaming |

## Estructura

```
python/
  download_era5land.py   # Descarga medias mensuales de t2m (subset Canarias)
  anomalies.py           # Anomalías vs. 1991-2020 y warming stripes
  requirements.txt
java/
  pom.xml
  src/main/java/dev/javier/climate/NcValidator.java
data/
  raw/                   # NetCDF descargados (no se versionan)
  processed/             # Salidas (CSV, PNG)
```

## Fase 1: puesta en marcha

### 1. Credenciales de Copernicus CDS
1. Crea cuenta en https://cds.climate.copernicus.eu
2. Entra en el dataset **ERA5-Land monthly averaged data from 1950 to present** y
   **acepta la licencia** (pestaña Download, abajo). Sin esto la API devuelve error.
3. Copia tu clave desde tu perfil y crea `~/.cdsapirc`:
   ```
   url: https://cds.climate.copernicus.eu/api
   key: <TU-CLAVE-PERSONAL>
   ```

### 2. Python
```bash
cd python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python download_era5land.py --start 1950 --end 2025
python anomalies.py
```
Salidas en `data/processed/`: `annual_anomaly_canarias.csv` y `warming_stripes_canarias.png`.

### 3. Java (validador de calidad)
```bash
cd java
mvn -q package
java -jar target/nc-validator.jar ../data/raw/era5land_t2m_monthly_1950_2025.nc
```
Devuelve código de salida 0 si el fichero es válido y 1 si no, de modo que más
adelante se puede usar como puerta de calidad en el pipeline (Job de Kubernetes
o paso de CI).

## Notas
- ERA5-Land tiene datos solo sobre tierra: el mar aparece como valores vacíos.
  La temperatura del mar se trata en una fase posterior con Copernicus Marine.
- Fuente de datos: Copernicus Climate Change Service (C3S). Cita siempre la
  fuente y respeta la licencia.

## Hoja de ruta
- [x] Fase 1: ingesta, exploración y validación
- [x] Fase 2: infraestructura (kind + Terraform + MinIO) e ingesta a bronze con Job/CronJob
- [ ] Fase 3: pipeline de indicadores orquestado (silver, gold y orquestación con Dagster hechos)
- [ ] Fase 4: API (Java/Spring Boot) y mapa web
- [ ] Fase 5: EUMETSAT (LST casi en tiempo real)
- [ ] Fase 6: nube real, GitOps y observabilidad
