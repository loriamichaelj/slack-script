output "log_bucket" {
  description = "Org-wide log bucket. Query it in Logs Explorer or Log Analytics."
  value       = google_logging_project_bucket_config.org.id
}

output "trace_scope" {
  description = "Org-wide trace scope. Make it the default with the gcloud step in README.md."
  value       = google_observability_trace_scope.org.name
}

output "monitored_projects" {
  description = "Projects whose metrics the scoping project can read."
  value       = sort(keys(google_monitoring_monitored_project.org))
}
