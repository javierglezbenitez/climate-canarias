# Secretos que consumen los Jobs de ingesta. Terraform los crea desde variables
# sensibles, así que nunca aparecen en los manifiestos YAML ni en git.

resource "kubernetes_secret" "cds_credentials" {
  metadata {
    name      = "cds-credentials"
    namespace = kubernetes_namespace.climate.metadata[0].name
  }

  data = {
    CDSAPI_URL = var.cds_api_url
    CDSAPI_KEY = var.cds_api_key
  }
}

# De momento se usa el usuario administrador de MinIO. Mejora pendiente: crear un
# usuario/access key propio de la ingesta con permisos solo sobre el bucket bronze.
resource "kubernetes_secret" "s3_credentials" {
  metadata {
    name      = "s3-credentials"
    namespace = kubernetes_namespace.climate.metadata[0].name
  }

  data = {
    S3_ENDPOINT   = "http://minio.${var.namespace}.svc.cluster.local:9000"
    S3_ACCESS_KEY = var.minio_root_user
    S3_SECRET_KEY = var.minio_root_password
  }
}
