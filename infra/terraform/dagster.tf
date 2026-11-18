# Dagster (orquestador) desplegado con su chart oficial de Helm.
#
# La base de datos de Dagster NO usa el PostgreSQL incluido en el chart: se despliega aquí
# un PostgreSQL oficial (imagen postgres de Docker Hub). Así controlamos la imagen (el
# problema que tuvimos con MinIO) y esta base se podrá reutilizar o ampliar más adelante.

resource "random_password" "dagster_db" {
  length  = 24
  special = false
}

resource "kubernetes_secret" "dagster_db" {
  metadata {
    name      = "dagster-db"
    namespace = kubernetes_namespace.climate.metadata[0].name
  }

  data = {
    POSTGRES_PASSWORD = random_password.dagster_db.result
  }
}

resource "kubernetes_service" "dagster_db" {
  metadata {
    name      = "dagster-db"
    namespace = kubernetes_namespace.climate.metadata[0].name
  }

  spec {
    cluster_ip = "None" # headless, necesario para el StatefulSet
    selector = {
      app = "dagster-db"
    }
    port {
      port        = 5432
      target_port = 5432
    }
  }
}

resource "kubernetes_stateful_set_v1" "dagster_db" {
  metadata {
    name      = "dagster-db"
    namespace = kubernetes_namespace.climate.metadata[0].name
  }

  spec {
    service_name = kubernetes_service.dagster_db.metadata[0].name
    replicas     = 1

    selector {
      match_labels = {
        app = "dagster-db"
      }
    }

    template {
      metadata {
        labels = {
          app = "dagster-db"
        }
      }

      spec {
        container {
          name  = "postgres"
          image = "postgres:16-alpine"

          port {
            container_port = 5432
          }

          env {
            name  = "POSTGRES_USER"
            value = "dagster"
          }
          env {
            name  = "POSTGRES_DB"
            value = "dagster"
          }
          env {
            name = "POSTGRES_PASSWORD"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.dagster_db.metadata[0].name
                key  = "POSTGRES_PASSWORD"
              }
            }
          }
          env {
            name  = "PGDATA"
            value = "/var/lib/postgresql/data/pgdata"
          }

          volume_mount {
            name       = "data"
            mount_path = "/var/lib/postgresql/data"
          }

          readiness_probe {
            exec {
              command = ["pg_isready", "-U", "dagster", "-d", "dagster"]
            }
            initial_delay_seconds = 5
            period_seconds        = 5
          }

          resources {
            requests = {
              cpu    = "50m"
              memory = "128Mi"
            }
            limits = {
              memory = "512Mi"
            }
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "data"
      }
      spec {
        access_modes = ["ReadWriteOnce"]
        resources {
          requests = {
            storage = "2Gi"
          }
        }
      }
    }
  }
}

resource "helm_release" "dagster" {
  name       = "dagster"
  namespace  = kubernetes_namespace.climate.metadata[0].name
  repository = "https://dagster-io.github.io/helm"
  chart      = "dagster"
  version    = var.dagster_chart_version

  wait    = true
  timeout = 900

  # La contraseña va aparte, como valor sensible, para que no aparezca en los planes de Terraform.
  set_sensitive {
    name  = "postgresql.postgresqlPassword"
    value = random_password.dagster_db.result
  }

  values = [yamlencode({
    # Base de datos externa (la que desplegamos arriba)
    postgresql = {
      enabled            = false
      postgresqlHost     = "dagster-db"
      postgresqlUsername = "dagster"
      postgresqlDatabase = "dagster"
      service = {
        port = 5432
      }
    }

    # Nuestro código: la imagen `climate-pipeline` (cargada en kind con `kind load`)
    "dagster-user-deployments" = {
      enabled        = true
      enableSubchart = true
      deployments = [{
        name = "climate-pipeline"
        image = {
          repository = "climate-pipeline"
          tag        = var.pipeline_image_tag
          pullPolicy = "IfNotPresent"
        }
        dagsterApiGrpcArgs = ["-m", "orchestration.definitions"]
        port = 3030
        envSecrets = [
          { name = kubernetes_secret.cds_credentials.metadata[0].name },
          { name = kubernetes_secret.s3_credentials.metadata[0].name },
        ]
      }]
    }

    # Cada ejecución es un Job de Kubernetes con la misma imagen y los mismos secretos
    runLauncher = {
      type = "K8sRunLauncher"
      config = {
        k8sRunLauncher = {
          imagePullPolicy = "IfNotPresent"
          envSecrets = [
            { name = kubernetes_secret.cds_credentials.metadata[0].name },
            { name = kubernetes_secret.s3_credentials.metadata[0].name },
          ]
        }
      }
    }
  })]

  depends_on = [kubernetes_stateful_set_v1.dagster_db]
}
