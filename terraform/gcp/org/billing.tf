# Each billing account's Standard usage cost export goes to a dataset in an org project.
# The job only reads them: the query itself runs as a job in the scoping project, where the
# runtime account can already run BigQuery jobs.
resource "google_bigquery_dataset_iam_member" "runtime_reads_billing" {
  for_each   = toset(var.billing_datasets)
  project    = split(".", each.value)[0]
  dataset_id = split(".", each.value)[1]
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:anomaly-runtime@${var.project_id}.iam.gserviceaccount.com"
}

moved {
  from = google_bigquery_dataset_iam_member.runtime_reads_billing
  to   = google_bigquery_dataset_iam_member.runtime_reads_billing["tensile-runway-511902-q9.shiptrack_billing_export"]
}
