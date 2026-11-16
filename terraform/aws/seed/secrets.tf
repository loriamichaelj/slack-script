# Slack webhooks, created here so tearing down DEV keeps them and their values.
# Terraform creates the secrets but never their values, so no webhook URL lands in
# state. Add a value by hand (see README.md); the runtime role can read them.

locals {
  webhook_secrets = toset(["slack-webhook", "slack-routine-webhook"])
}

resource "aws_secretsmanager_secret" "webhook" {
  # checkov:skip=CKV_AWS_149: the default AWS-managed key is enough for a webhook URL
  # checkov:skip=CKV2_AWS_57: a webhook URL cannot be rotated automatically
  for_each = local.webhook_secrets

  name                    = each.value
  recovery_window_in_days = 7

  lifecycle {
    prevent_destroy = true
  }
}
