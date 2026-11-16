# The function runs a container image from the ECR repository SEED created. It starts on the
# latest image, and the deploy-aws-dev workflow points it at each new commit's image.
# Terraform ignores the image after creation, so deploys and applies never undo each other.
data "aws_ecr_repository" "app" {
  name = "anomaly-alerts"
}

resource "aws_cloudwatch_log_group" "lambda" {
  # checkov:skip=CKV_AWS_158: the default CloudWatch Logs encryption is enough
  # checkov:skip=CKV_AWS_338: logs are kept for a short time on purpose, to keep the bill low
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "app" {
  # checkov:skip=CKV_AWS_50: X-Ray tracing is not needed for a scheduled job
  # checkov:skip=CKV_AWS_115: reserved concurrency can fail on new accounts with a low quota, and the schedules never overlap in practice
  # checkov:skip=CKV_AWS_116: a failed run is retried by the next schedule, and failures show in the heartbeat
  # checkov:skip=CKV_AWS_117: the function only calls public AWS APIs, so it needs no VPC
  # checkov:skip=CKV_AWS_173: the environment holds secret names and a config path, not secrets
  # checkov:skip=CKV_AWS_272: code signing is not worth it for a single-owner dev function
  function_name = local.function_name
  role          = local.runtime_role
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.app.repository_url}:latest"
  architectures = ["x86_64"] # the CI runners build x86_64 images
  timeout       = 300
  memory_size   = 256

  environment {
    variables = {
      ANOMALY_CONFIG                      = "s3://${aws_s3_bucket.app.id}/${aws_s3_object.config.key}"
      SLACK_WEBHOOK_URL_SECRET_ID         = "slack-webhook"
      SLACK_ROUTINE_WEBHOOK_URL_SECRET_ID = "slack-routine-webhook"
    }
  }

  lifecycle {
    ignore_changes = [image_uri]
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
