# Keyless access for GitHub Actions. AWS validates the token against GitHub's
# certificate chain, so no thumbprint is set.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  # One subject per GitHub environment: the environment's own protection rules
  # (reviewers, branch policy) decide who can reach each role.
  github_subjects = {
    seed = "${local.subject_prefix}:environment:SEED"
    dev  = "${local.subject_prefix}:environment:DEV"
    ci   = "${local.subject_prefix}:environment:CI"
  }

  # SEED applies the seed, DEV applies dev, and CI plans (read-only) and destroys dev.
  role_subjects = {
    seed-admin   = [local.github_subjects.seed]
    dev-deployer = [local.github_subjects.dev, local.github_subjects.ci]
    tf-planner   = [local.github_subjects.ci]
  }
}

data "aws_iam_policy_document" "github_trust" {
  for_each = local.role_subjects

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = each.value
    }
  }
}

resource "aws_iam_role" "github" {
  for_each = local.role_subjects

  name                 = each.key
  assume_role_policy   = data.aws_iam_policy_document.github_trust[each.key].json
  max_session_duration = 3600
}
