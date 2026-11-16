locals {
  tags = merge({
    app        = "slack-anomaly"
    env        = "seed"
    managed_by = "terraform"
    repo       = var.github_repo
  }, var.tags)

  # Subject prefix GitHub puts in every OIDC token for this repo, by immutable ID.
  subject_prefix = "repo:${var.github_owner}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}"
}

data "aws_caller_identity" "current" {}
