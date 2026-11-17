variable "cluster_name" {
  description = "Nombre del cluster kind"
  type        = string
  default     = "climate"
}

variable "namespace" {
  description = "Namespace donde viven los componentes de la plataforma"
  type        = string
  default     = "climate"
}

variable "worker_nodes" {
  description = "Número de nodos worker (cada uno es un contenedor Docker; súbelo solo si tienes RAM)"
  type        = number
  default     = 1
}

variable "minio_root_user" {
  description = "Usuario administrador de MinIO"
  type        = string
  default     = "climateadmin"
}

variable "minio_root_password" {
  description = "Contraseña de MinIO (mínimo 8 caracteres). Defínela en terraform.tfvars o con TF_VAR_minio_root_password"
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.minio_root_password) >= 8
    error_message = "MinIO exige al menos 8 caracteres."
  }
}

variable "minio_image_repository" {
  description = "Imagen del servidor S3. quay.io/minio/minio ya no se puede descargar sin cuenta; esta es una réplica comunitaria que incluye también el cliente mc"
  type        = string
  default     = "docker.io/pgsty/silo"
}

variable "minio_image_tag" {
  description = "Tag de la imagen (compruébalo con docker pull antes de aplicar)"
  type        = string
  default     = "RELEASE.2026-10-26T00-00-00Z"
}

variable "minio_storage_size" {
  description = "Tamaño del volumen persistente de MinIO"
  type        = string
  default     = "5Gi"
}
