terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0" # trace scopes need 7.x; seed and dev stay on 6.x
    }
  }

  # Shares the SEED state bucket under its own prefix. Pass the bucket at init time.
  backend "gcs" {
    prefix = "org"
  }
}

provider "google" {
  project = var.project_id
}
