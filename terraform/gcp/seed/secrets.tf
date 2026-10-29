# Slack webhooks, created here so tearing down DEV keeps them and their values.
# Terraform creates the secrets but never their values, so no webhook URL lands in
# state. Add a version by hand (see README.md); DEV grants the jobs read access.

locals {
  webhook_secrets = toset(["slack-webhook", "slack-routine-webhook"])
}

resource "google_secret_manager_secret" "webhook" {
  for_each = local.webhook_secrets

  secret_id = each.value

  replication {
    auto {}
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

# These secrets were first created by DEV. Adopt them as they are, values included.
import {
  for_each = local.webhook_secrets

  to = google_secret_manager_secret.webhook[each.value]
  id = "projects/${var.project_id}/secrets/${each.value}"
}
