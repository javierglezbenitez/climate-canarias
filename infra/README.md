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
