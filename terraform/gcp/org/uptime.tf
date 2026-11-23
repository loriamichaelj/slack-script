# Public sites checked from outside every 5 minutes, from 3 regions. The alert job reads
# monitoring.googleapis.com/uptime_check/check_passed in the scoping project and alerts when
# most regions fail. Uptime checks are free up to 1 million runs a month per billing account;
# one site uses about 26,000.
resource "google_monitoring_uptime_check_config" "site" {
  for_each         = var.uptime_hosts
  project          = var.project_id
  display_name     = each.key
  timeout          = "10s"
  period           = "300s"
  selected_regions = ["USA", "EUROPE", "ASIA_PACIFIC"]

  http_check {
    path         = "/"
    port         = 443
    use_ssl      = true
    validate_ssl = true
    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = each.value
    }
  }
}
