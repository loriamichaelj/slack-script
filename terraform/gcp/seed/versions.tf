terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # The bucket is passed at init time so this file works before and after the
  # bootstrap. See README.md for the first-apply steps.
  backend "gcs" {
    prefix = "seed"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = local.labels
}
