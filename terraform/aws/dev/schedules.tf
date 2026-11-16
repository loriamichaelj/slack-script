# One Lambda, one schedule per job. The event picks the command.
locals {
  jobs = {
    "anomaly-run" = {
      schedule = "cron(0/5 * * * ? *)" # every 5 minutes, matching the metric period
      input    = { command = "run" }
    }
    "routine-heartbeat" = {
      schedule = "cron(0 0/6 * * ? *)"
      input    = { command = "routine", kind = "heartbeat" }
    }
    "routine-digest" = {
      schedule = "cron(0 9 * * ? *)"
      input    = { command = "routine", kind = "digest" }
    }
    "routine-cost" = {
      schedule = "cron(30 9 * * ? *)"
      input    = { command = "routine", kind = "cost" }
    }
  }
}

# EventBridge Scheduler starts the Lambda as this role, which may only invoke it.
data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "slack-anomaly-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.app.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "invoke-anomaly-alerts"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

resource "aws_scheduler_schedule" "job" {
  # checkov:skip=CKV_AWS_297: the input is only a command name, so a customer-managed key would add cost and nothing else
  for_each = local.jobs

  name                         = each.key
  schedule_expression          = each.value.schedule
  schedule_expression_timezone = var.time_zone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.app.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode(each.value.input)

    # A retry could post the same alert twice. The next run picks up what was missed.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
