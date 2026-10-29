# Org-wide logs: an organization sink copies every log entry from every project in
# the org, including projects created later, into one bucket in the scoping project.
# Log Analytics lets you query it with SQL. Copies are billed at ingestion again.

locals {
  log_bucket_id = "org-logs"
}

resource "google_logging_project_bucket_config" "org" {
  project          = var.project_id
  location         = "global"
  bucket_id        = local.log_bucket_id
  description      = "All logs from every project in the org, kept ${var.log_retention_days} days."
  retention_days   = var.log_retention_days
  enable_analytics = true
}

resource "google_logging_organization_sink" "all" {
  name             = "org-logs"
  description      = "Every log entry from every project in the org."
  org_id           = var.org_id
  include_children = true
  destination      = "logging.googleapis.com/${google_logging_project_bucket_config.org.id}"
  # No filter: all logs.
}

# The sink's own identity may write to this one bucket and nothing else.
resource "google_project_iam_member" "org_sink_writer" {
  project = var.project_id
  role    = "roles/logging.bucketWriter"
  member  = google_logging_organization_sink.all.writer_identity

  condition {
    title      = "org-logs bucket only"
    expression = "resource.name.endsWith(\"locations/global/buckets/${local.log_bucket_id}\")"
  }
}
