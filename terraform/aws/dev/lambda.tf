# The Lambda starts with a placeholder. The deploy-aws-dev workflow uploads the real
# code, and Terraform ignores the code after creation, so deploys and applies never
# undo each other.
data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/.terraform/placeholder.zip"

  source {
    filename = "anomaly_alerts/handler.py"
    content  = <<-EOT
      def lambda_handler(event, context):
          return {"placeholder": True}
    EOT
  }
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
  runtime       = "python3.12"
  architectures = ["x86_64"] # matches scripts/build-lambda.sh
  handler       = "anomaly_alerts.handler.lambda_handler"
  timeout       = 300
  memory_size   = 256

  filename         = data.archive_file.placeholder.output_path
  source_code_hash = data.archive_file.placeholder.output_base64sha256

  environment {
    variables = {
      ANOMALY_CONFIG                      = "s3://${aws_s3_bucket.app.id}/${aws_s3_object.config.key}"
      SLACK_WEBHOOK_URL_SECRET_ID         = "slack-webhook"
      SLACK_ROUTINE_WEBHOOK_URL_SECRET_ID = "slack-routine-webhook"
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
