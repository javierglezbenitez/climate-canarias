# Infraestructura (Fase 2)

Cluster Kubernetes local con **kind** + **MinIO** (data lake S3) desplegados con **Terraform**.

## Requisitos
Docker Desktop (arrancado), kubectl, kind, Terraform y Helm.

## Despliegue
```powershell
cd infra\terraform
copy terraform.tfvars.example terraform.tfvars   # edita la contraseña
terraform init
terraform plan
terraform apply
```
La primera vez tarda unos minutos (descarga la imagen del nodo y el chart de MinIO).

## Comprobar
```powershell
kubectl config get-contexts            # debe aparecer kind-climate
kubectl get nodes
kubectl -n climate get pods
kubectl -n climate port-forward svc/minio-console 9001:9001
```
Consola de MinIO en http://localhost:9001 (usuario `climateadmin` y tu contraseña).
Deben existir los buckets `bronze`, `silver` y `gold`.

## Destruir (y recuperar RAM)
```powershell
terraform destroy
```

## Ingesta a bronze (Fase 2, paso 2)

1. Añade tu clave del CDS a `infra/terraform/terraform.tfvars` (`cds_api_key = "..."`) y ejecuta
   `terraform apply`: crea los Secrets `cds-credentials` y `s3-credentials` en el cluster.
2. Construye la imagen y cárgala en kind (el cluster no ve las imágenes locales de Docker):
   ```powershell
   cd python
   docker build -t climate-ingest:0.1.0 -f Dockerfile.ingest .
   kind load docker-image climate-ingest:0.1.0 --name climate
   ```
3. Carga inicial del histórico:
   ```powershell
   cd ..
   kubectl apply -f k8s\ingest-backfill-job.yaml
   kubectl -n climate logs -f job/ingest-backfill
   ```
4. Comprueba en la consola de MinIO que `bronze/era5land/t2m_monthly/` tiene los NetCDF.
5. Actualización mensual automática:
   ```powershell
   kubectl apply -f k8s\ingest-cronjob.yaml
   kubectl -n climate create job --from=cronjob/ingest-monthly ingest-prueba   # lanzarlo ya, para probar
   ```

## Capa silver (Fase 3, paso 1)

Valida con Java cada NetCDF de `bronze` y los unifica en un cubo Zarr en `silver`.
La imagen se construye desde la **raíz del repositorio** (necesita `java/` y `python/`):
```powershell
cd C:\Users\cgsos\Documents\climate-canarias
docker build -t climate-pipeline:0.2.0 -f python\Dockerfile.pipeline .
kind load docker-image climate-pipeline:0.2.0 --name climate
kubectl -n climate delete job silver-transform --ignore-not-found
kubectl apply -f k8s\silver-job.yaml
kubectl -n climate logs -f job/silver-transform
```
Resultado: `silver/era5land/t2m_monthly.zarr` en MinIO. Si algún NetCDF no pasa el validador,
el Job aborta sin escribir nada (puerta de calidad estricta).

## Capa gold (Fase 3, paso 2)

Calcula anomalías (base 1991-2020), tendencias y rejillas por década y las guarda en Parquet
en `gold/era5land/indicators/`. Usa la **misma imagen** que silver (`climate-pipeline`):
```powershell
kubectl -n climate delete job gold-indicators --ignore-not-found
kubectl apply -f k8s\gold-job.yaml
kubectl -n climate logs -f job/gold-indicators
```
Los años incompletos (el año en curso) se marcan y no entran en tendencias ni en medias por década.
