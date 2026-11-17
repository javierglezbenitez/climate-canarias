output "cluster_name" {
  value = kind_cluster.this.name
}

output "namespace" {
  value = kubernetes_namespace.climate.metadata[0].name
}

output "minio_s3_endpoint_in_cluster" {
  description = "Endpoint S3 para pods dentro del cluster"
  value       = "http://minio.${var.namespace}.svc.cluster.local:9000"
}

output "minio_port_forward_hint" {
  description = "Comando para abrir la consola de MinIO en tu navegador (http://localhost:9001)"
  value       = "kubectl -n ${var.namespace} port-forward svc/minio-console 9001:9001"
}
