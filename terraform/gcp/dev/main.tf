# Identities come from SEED; DEV only uses them. Built from names, not looked up,
# so the deployer needs no read access to service accounts.
locals {
  runtime_sa = "anomaly-runtime@${var.project_id}.iam.gserviceaccount.com"
  planner_sa = "tf-planner@${var.project_id}.iam.gserviceaccount.com"
  image_repo = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/anomaly-alerts"
  mount_path = "/mnt/app"
}

resource "google_artifact_registry_repository" "images" {
  # checkov:skip=CKV_GCP_84: images hold no customer data; Google-managed encryption is enough
  repository_id = "anomaly-alerts"
  format        = "DOCKER"
  location      = var.region
  description   = "anomaly-alerts job images, pushed by the deploy-dev workflow."

  # Keep the last few images so a rollback is possible, delete the rest.
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s"
    }
  }
}

# Holds the job config and the cooldown state, mounted into every job.
resource "google_storage_bucket" "app" {
  # checkov:skip=CKV_GCP_62: access logging needs a separate log bucket, not worth it for one job's config and state
  # checkov:skip=CKV_GCP_78: the state file is rewritten every run and rebuilds itself if lost; versioning would only grow the bucket
  name     = "${var.project_id}-anomaly-app"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true # DEV is meant to be torn down
}

resource "google_storage_bucket_object" "config" {
  bucket       = google_storage_bucket.app.name
  name         = "config.yaml"
  content_type = "text/yaml"
  content = templatefile("${path.module}/config.yaml.tftpl", {
    project_id    = var.project_id
    billing_table = var.billing_table
    mount_path    = local.mount_path
  })
}

# The jobs read the config and read and write the state file.
resource "google_storage_bucket_iam_member" "runtime_app" {
  bucket = google_storage_bucket.app.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${local.runtime_sa}"
}

# The plan workflow reads the config object to compare it.
resource "google_storage_bucket_iam_member" "planner_app" {
  for_each = toset(["roles/storage.legacyBucketReader", "roles/storage.objectViewer"])

  bucket = google_storage_bucket.app.name
  role   = each.value
  member = "serviceAccount:${local.planner_sa}"
}
