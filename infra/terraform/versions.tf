terraform {
  required_version = ">= 1.6.0"

  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = "~> 0.6"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.14" # la sintaxis de este fichero es la de helm 2.x
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
