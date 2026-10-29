# Slack webhooks. Terraform creates the secrets but never their values, so no URL
# lands in state. Add a version by hand after the first apply (see README.md);
# until then, executions fail to start.
resource "google_secret_manager_secret" "webhook" {
  for_each = toset(["slack-webhook", "slack-routine-webhook"])

  secret_id = each.value

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_webhook" {
  for_each = google_secret_manager_secret.webhook

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.runtime_sa}"
}
