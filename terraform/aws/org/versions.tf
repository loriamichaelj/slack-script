terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Shares the SEED state bucket under its own key. Pass the bucket at init time.
  backend "s3" {
    key          = "org/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "anomaly-alerts"
      app        = "anomaly-alerts"
      env        = "org"
      managed_by = "terraform"
      repo       = var.github_repo
    }
  }
}

data "aws_caller_identity" "current" {}
