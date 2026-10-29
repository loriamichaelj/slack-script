output "image_repository" {
  description = "Where deploy-dev pushes images."
  value       = local.image_repo
}

output "jobs" {
  description = "Cloud Run jobs and their schedules."
  value       = { for name, j in local.jobs : name => j.schedule }
}

output "app_bucket" {
  description = "Bucket mounted into the jobs: config.yaml and state/alerts.json."
  value       = google_storage_bucket.app.name
}

output "webhook_secrets" {
  description = "Add a version to each with the Slack webhook URL (see README.md)."
  value       = [for s in google_secret_manager_secret.webhook : s.secret_id]
}
