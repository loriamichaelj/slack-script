# One multi-region trail for the account: every management event in every region, kept in S3
# for a year and sent to CloudWatch Logs, where metric filters (audit.tf) turn the events that
# matter into numbers. The first copy of management events is free; the log group's ingestion
# is a few cents a month at this account's volume.

locals {
  trail_name = "platform-audit"
  bucket     = "platform-audit-trail-${data.aws_caller_identity.current.account_id}"
  trail_arn  = "arn:aws:cloudtrail:${var.region}:${data.aws_caller_identity.current.account_id}:trail/${local.trail_name}"
}

resource "aws_s3_bucket" "trail" {
  # checkov:skip=CKV_AWS_144: one copy in one region is enough for a personal account's audit log
  # checkov:skip=CKV_AWS_145: SSE-S3 encrypts the files; a customer managed key costs $1 a month and adds nothing here
  # checkov:skip=CKV_AWS_18: access logging of the audit bucket would need a second bucket; CloudTrail data events can cover it later
  # checkov:skip=CKV2_AWS_62: nothing needs to react to new log files; the CloudWatch copy is what is watched
  bucket = local.bucket
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "trail" {
  bucket = aws_s3_bucket.trail.id
  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 encrypts the log files. A customer managed key would cost $1 a month, a fifth of the
# budget, and protects nothing more for a single-person account.
#trivy:ignore:AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration {
      days = var.bucket_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "trail_bucket" {
  statement {
    sid       = "CloudTrailAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.trail.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
  statement {
    sid       = "CloudTrailWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.trail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.trail.arn, "${aws_s3_bucket.trail.arn}/*"]
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

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = data.aws_iam_policy_document.trail_bucket.json
}

resource "aws_cloudwatch_log_group" "trail" {
  # checkov:skip=CKV_AWS_158: the default CloudWatch Logs encryption is enough; a customer managed key costs $1 a month
  # checkov:skip=CKV_AWS_338: the S3 copy keeps a year; the log group only needs enough for the metric filters and recent searches
  name              = "/aws/cloudtrail/${local.trail_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "trail_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
}

resource "aws_iam_role" "trail_logs" {
  name               = "platform-audit-trail-logs"
  description        = "Lets the platform-audit trail write to its CloudWatch log group."
  assume_role_policy = data.aws_iam_policy_document.trail_assume.json
}

data "aws_iam_policy_document" "trail_logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.trail.arn}:log-stream:*"]
  }
}

resource "aws_iam_role_policy" "trail_logs" {
  name   = "write-trail-log-group"
  role   = aws_iam_role.trail_logs.id
  policy = data.aws_iam_policy_document.trail_logs.json
}

#trivy:ignore:AWS-0015
resource "aws_cloudtrail" "platform" {
  # checkov:skip=CKV_AWS_35: SSE-S3 encrypts the files; a customer managed key costs $1 a month and adds nothing here
  # checkov:skip=CKV_AWS_252: alerts come from the metric filters, not from a notice per log file
  name                          = local.trail_name
  s3_bucket_name                = aws_s3_bucket.trail.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  cloud_watch_logs_group_arn    = "${aws_cloudwatch_log_group.trail.arn}:*"
  cloud_watch_logs_role_arn     = aws_iam_role.trail_logs.arn

  depends_on = [aws_s3_bucket_policy.trail, aws_iam_role_policy.trail_logs]
}
