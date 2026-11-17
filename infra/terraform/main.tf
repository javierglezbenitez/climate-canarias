# 1. Cluster Kubernetes local con kind (nodos = contenedores Docker)
resource "kind_cluster" "this" {
  name           = var.cluster_name
  wait_for_ready = true

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"
    }

    dynamic "node" {
      for_each = range(var.worker_nodes)
      content {
        role = "worker"
      }
    }
  }
}

# Los providers de Kubernetes y Helm se configuran con las credenciales
# del cluster que acaba de crear el recurso anterior.
provider "kubernetes" {
  host                   = kind_cluster.this.endpoint
  client_certificate     = kind_cluster.this.client_certificate
  client_key             = kind_cluster.this.client_key
  cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
}

provider "helm" {
  kubernetes {
    host                   = kind_cluster.this.endpoint
    client_certificate     = kind_cluster.this.client_certificate
    client_key             = kind_cluster.this.client_key
    cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
  }
}

# 2. Namespace de la plataforma
resource "kubernetes_namespace" "climate" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/part-of" = "climate-canarias"
    }
  }

  depends_on = [kind_cluster.this]
}

# 3. MinIO: data lake compatible con S3 (capas bronze / silver / gold)
resource "helm_release" "minio" {
  name       = "minio"
  namespace  = kubernetes_namespace.climate.metadata[0].name
  repository = "https://charts.min.io/"
  chart      = "minio"
  # Tras el primer despliegue, fija aquí la versión exacta que se instaló
  # (mira `helm list -n climate`) para que el entorno sea reproducible.

  wait    = true
  timeout = 600

  values = [yamlencode({
    mode     = "standalone"
    replicas = 1

    # MinIO retiró el acceso público a quay.io/minio/minio (401 UNAUTHORIZED),
    # así que usamos una imagen alternativa compatible con el chart.
    image = {
      repository = var.minio_image_repository
      tag        = var.minio_image_tag
    }
    mcImage = {
      repository = var.minio_image_repository
      tag        = var.minio_image_tag
    }

    rootUser     = var.minio_root_user
    rootPassword = var.minio_root_password

    persistence = {
      size = var.minio_storage_size
    }

    resources = {
      requests = {
        memory = "256Mi"
      }
    }

    buckets = [
      { name = "bronze", policy = "none", purge = false },
      { name = "silver", policy = "none", purge = false },
      { name = "gold", policy = "none", purge = false },
    ]
  })]
}
