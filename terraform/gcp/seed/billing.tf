# Cloud Billing export target. Lives in SEED so destroying DEV keeps the billing
# history. Turning the export on is a console step (see README.md); there is no API.

resource "google_bigquery_dataset" "billing_export" {
  # checkov:skip=CKV_GCP_81: billing data is encrypted with Google-managed keys; a customer-managed key adds a KMS key to run for no gain here
  dataset_id    = "billing_export"
  friendly_name = "Cloud Billing export"
  description   = "Standard usage cost export for the billing account. Read by the cost report."
  location      = "US"

  delete_contents_on_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

# The cost report queries the export: read the dataset, and run jobs in this project.
resource "google_bigquery_dataset_iam_member" "runtime_reads_billing" {
  dataset_id = google_bigquery_dataset.billing_export.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_bigquery_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
