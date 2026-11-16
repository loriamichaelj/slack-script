terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # The bucket is created by SEED and passed at init time.
  backend "s3" {
    key          = "dev/terraform.tfstate"
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
      env        = "dev"
      managed_by = "terraform"
      repo       = "slack-script"
    }
  }
}
