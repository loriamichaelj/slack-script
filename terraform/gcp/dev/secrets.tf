# The Slack webhook secrets are created by SEED, so tearing down DEV keeps them and
# their values. DEV only lets the jobs read them.
locals {
  webhook_secrets = toset(["slack-webhook", "slack-routine-webhook"])
}

# DEV created these secrets at first. Hand them to SEED without deleting them.
removed {
  from = google_secret_manager_secret.webhook

  lifecycle {
    destroy = false
  }
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_webhook" {
  for_each = local.webhook_secrets

  secret_id = "projects/${var.project_id}/secrets/${each.value}"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.runtime_sa}"
}
