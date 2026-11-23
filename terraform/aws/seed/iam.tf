# seed-admin manages this directory, which creates IAM roles and the OIDC provider,
# so it needs administrator rights. Only the SEED environment (reviewer, dev branch) can assume it.
resource "aws_iam_role_policy_attachment" "seed_admin" {
  # checkov:skip=CKV_AWS_274: the seed creates IAM roles and the OIDC provider, which needs administrator rights; only the SEED environment can assume this role
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
  # checkov:skip=CKV_AWS_356: CloudWatch metric reads, Cost Explorer and Organizations reads do not support resource-level permissions
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

  # The app bucket (config, cooldown state) is created by DEV; this role only reads the
  # config and reads and writes the state in it.
  statement {
    sid       = "AppBucketObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:aws:s3:::${var.name_prefix}-anomaly-app/*"]
  }

  statement {
    sid       = "AppBucketList"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.name_prefix}-anomaly-app"]
  }

  # The webhook URLs and the bot token are free SSM SecureString parameters under /anomaly-alerts.
  # Terraform only grants the read: the parameters are created by hand (see README.md), because a
  # parameter that Terraform manages would have its value read back into the state file.
  statement {
    sid       = "ReadWebhookParameters"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/anomaly-alerts/*"]
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
  # checkov:skip=CKV_AWS_109: role and policy management is limited to names under slack-anomaly-*
  # checkov:skip=CKV_AWS_110: iam:PassRole is limited to the runtime role and IAM writes to slack-anomaly-* names
  # checkov:skip=CKV_AWS_111: writes are limited to this app's Lambda, schedules, buckets and roles
  # checkov:skip=CKV_AWS_356: Lambda, EventBridge and log actions are managed by name patterns the plan cannot know in advance
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
    actions   = ["s3:CreateBucket", "s3:DeleteBucket", "s3:Get*", "s3:Put*", "s3:List*", "s3:DeleteObject*"]
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

  # The Lambda runs as the runtime role, and EventBridge Scheduler starts it as the scheduler role.
  statement {
    sid     = "PassRoles"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.runtime.arn,
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/slack-anomaly-scheduler",
    ]
  }

  statement {
    sid       = "ReadForPlan"
    actions   = ["iam:Get*", "iam:List*"]
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
