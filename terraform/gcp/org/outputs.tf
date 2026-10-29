output "monitored_projects" {
  description = "Projects whose metrics the scoping project can read."
  value       = sort(keys(google_monitoring_monitored_project.org))
}
