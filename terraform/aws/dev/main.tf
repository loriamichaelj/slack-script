data "aws_caller_identity" "current" {}

# The runtime role and webhook secrets come from SEED. Built from names, not looked up.
locals {
  account_id    = data.aws_caller_identity.current.account_id
  runtime_role  = "arn:aws:iam::${local.account_id}:role/anomaly-runtime"
  function_name = "anomaly-alerts"
  app_bucket    = "${var.name_prefix}-anomaly-app"
}

# Holds the job config and the cooldown state, read and written by the Lambda.
resource "aws_s3_bucket" "app" {
  # checkov:skip=CKV_AWS_18: access logging needs a separate log bucket, not worth it for one function's config and state
  # checkov:skip=CKV_AWS_21: the state file is rewritten every run and rebuilds itself if lost; versioning would only grow the bucket
  # checkov:skip=CKV_AWS_144: cross-region replication is not worth it for dev
  # checkov:skip=CKV2_AWS_62: no event notifications are needed
  # checkov:skip=CKV_AWS_145: SSE-S3 is enough; a KMS key adds cost and a dependency
  bucket        = local.app_bucket
  force_destroy = true # DEV is meant to be torn down
}

#trivy:ignore:AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "app" {
  bucket = aws_s3_bucket.app.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "app" {
  bucket                  = aws_s3_bucket.app.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "app" {
  bucket = aws_s3_bucket.app.id

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "app_tls" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.app.arn, "${aws_s3_bucket.app.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "app" {
  bucket = aws_s3_bucket.app.id
  policy = data.aws_iam_policy_document.app_tls.json

  depends_on = [aws_s3_bucket_public_access_block.app]
}

resource "aws_s3_object" "config" {
  bucket       = aws_s3_bucket.app.id
  key          = "config.yaml"
  content_type = "text/yaml"
  content = templatefile("${path.module}/config.yaml.tftpl", {
    bucket           = aws_s3_bucket.app.id
    region           = var.region
    function_name    = local.function_name
    slack_channel_id = var.slack_channel_id
    time_zone        = var.time_zone
  })
}
