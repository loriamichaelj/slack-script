# Copy these into the GitHub environments as variables (not secrets, none are sensitive).

output "workload_identity_provider" {
  description = "Value for google-github-actions/auth workload_identity_provider."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "seed_admin_service_account" {
  description = "SEED environment variable GCP_SERVICE_ACCOUNT."
  value       = google_service_account.seed_admin.email
}

output "dev_deployer_service_account" {
  description = "DEV and CI environment variable GCP_SERVICE_ACCOUNT."
  value       = google_service_account.dev_deployer.email
}

output "tf_planner_service_account" {
  description = "CI environment variable GCP_PLAN_SERVICE_ACCOUNT."
  value       = google_service_account.tf_planner.email
}

output "runtime_service_account" {
  description = "Identity for the Cloud Run job, used by terraform/gcp/dev."
  value       = google_service_account.runtime.email
}

output "state_buckets" {
  description = "Terraform state buckets by environment."
  value       = { for k, b in google_storage_bucket.state : k => b.name }
}

output "webhook_secrets" {
  description = "Add a version to each with the Slack webhook URL (see README.md)."
  value       = [for s in google_secret_manager_secret.webhook : s.secret_id]
}

output "billing_export_dataset" {
  description = "Pick this dataset when turning on the Cloud Billing export to BigQuery."
  value       = "${var.project_id}.${google_bigquery_dataset.billing_export.dataset_id}"
}
