# seed-admin manages this directory, which creates IAM roles and the OIDC provider,
# so it needs administrator rights. Only the SEED environment (reviewer, dev branch) can assume it.
resource "aws_iam_role_policy_attachment" "seed_admin" {
  role       = aws_iam_role.github["seed-admin"].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# tf-planner reads everything and the state buckets, but cannot write or lock state.
resource "aws_iam_role_policy_attachment" "planner_read" {
  role       = aws_iam_role.github["tf-planner"].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# The jobs' identity at run time: read metrics and costs, read the two webhook secrets.
# DEV adds access to its app-state bucket.
data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name               = "anomaly-runtime"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "runtime_logs" {
  role       = aws_iam_role.runtime.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "runtime" {
  statement {
    sid = "ReadMetrics"
    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:ListMetrics",
      "cloudwatch:DescribeAlarms",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "ReadCosts"
    actions   = ["ce:GetCostAndUsage"]
    resources = ["*"]
  }

  # Org-wide metrics and cost: names the member accounts in reports.
  statement {
    sid = "ReadOrganization"
    actions = [
      "organizations:DescribeOrganization",
      "organizations:ListAccounts",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "ReadWebhooks"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for s in aws_secretsmanager_secret.webhook : s.arn]
  }
}

resource "aws_iam_policy" "runtime" {
  name   = "anomaly-runtime"
  policy = data.aws_iam_policy_document.runtime.json
}

resource "aws_iam_role_policy_attachment" "runtime" {
  role       = aws_iam_role.runtime.name
  policy_arn = aws_iam_policy.runtime.arn
}

# dev-deployer applies and destroys terraform/aws/dev: Lambda, its schedules, the app
# bucket, logs and the roles those need. IAM is limited to names under this app.
data "aws_iam_policy_document" "deployer" {
  statement {
    sid = "Workloads"
    actions = [
      "lambda:*",
      "events:*",
      "scheduler:*",
      "logs:*",
      "ecr:*",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "AppBuckets"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::${var.name_prefix}-*", "arn:aws:s3:::${var.name_prefix}-*/*"]
  }

  statement {
    sid = "AppRoles"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:UpdateRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:CreatePolicy",
      "iam:DeletePolicy",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:ListPolicyVersions",
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:TagPolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/slack-anomaly-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/slack-anomaly-*",
    ]
  }

  statement {
    sid       = "PassRuntimeRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.runtime.arn]
  }

  statement {
    sid       = "ReadForPlan"
    actions   = ["iam:Get*", "iam:List*", "secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy"]
    resources = ["*"]
  }

  statement {
    sid       = "DevState"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.state["dev"].arn, "${aws_s3_bucket.state["dev"].arn}/*"]
  }
}

resource "aws_iam_policy" "deployer" {
  name   = "dev-deployer"
  policy = data.aws_iam_policy_document.deployer.json
}

resource "aws_iam_role_policy_attachment" "deployer" {
  role       = aws_iam_role.github["dev-deployer"].name
  policy_arn = aws_iam_policy.deployer.arn
}
