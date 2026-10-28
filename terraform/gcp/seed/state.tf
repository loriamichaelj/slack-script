# Terraform state for SEED and DEV. Neither bucket is destroyed by the destroy
# workflows: they only run against DEV, and prevent_destroy guards a local destroy.
locals {
  state_buckets = {
    seed = "${var.project_id}-seed-tfstate"
    dev  = "${var.project_id}-dev-tfstate"
  }
}

resource "google_storage_bucket" "state" {
  for_each = local.state_buckets

  name     = each.value
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  labels = { env = each.key }

  versioning {
    enabled = true
  }

  # Keep recent history for recovery, drop old versions so the bucket stays small.
  lifecycle_rule {
    condition {
      num_newer_versions = 10
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  # checkov:skip=CKV_GCP_62: access logging needs a separate log bucket, which is not worth it for a single-user state bucket

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}
