terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # The bucket is created by SEED and passed at init time.
  backend "gcs" {
    prefix = "dev"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = {
    app        = "anomaly-alerts"
    env        = "dev"
    managed_by = "terraform"
    repo       = "slack-script"
  }
}
