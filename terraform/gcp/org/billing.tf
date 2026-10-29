# The billing account's Standard usage cost export already goes to a dataset in
# another org project. The job only reads it: the query itself runs as a job in the
# scoping project, where the runtime account can already run BigQuery jobs.

locals {
  billing_project = split(".", var.billing_dataset)[0]
  billing_dataset = split(".", var.billing_dataset)[1]
}

resource "google_bigquery_dataset_iam_member" "runtime_reads_billing" {
  project    = local.billing_project
  dataset_id = local.billing_dataset
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:anomaly-runtime@${var.project_id}.iam.gserviceaccount.com"
}
