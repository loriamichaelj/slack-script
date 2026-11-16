# Terraform state for SEED and DEV. Neither bucket is destroyed by the destroy
# workflows: they only run against DEV, and prevent_destroy guards a local destroy.
locals {
  state_buckets = {
    seed = "${var.name_prefix}-seed-tfstate"
    dev  = "${var.name_prefix}-dev-tfstate"
  }
}

resource "aws_s3_bucket" "state" {
  # checkov:skip=CKV_AWS_18: access logging needs a separate log bucket, which is not worth it for a single-user state bucket
  # checkov:skip=CKV_AWS_144: cross-region replication is not worth it for dev state
  # checkov:skip=CKV2_AWS_62: no event notifications are needed on a state bucket
  # checkov:skip=CKV_AWS_145: SSE-S3 is enough here; a KMS key adds cost and a dependency for the state itself
  for_each = local.state_buckets

  bucket        = each.value
  force_destroy = false

  tags = { env = each.key }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  for_each = aws_s3_bucket.state

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  for_each = aws_s3_bucket.state

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  for_each = aws_s3_bucket.state

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Keep recent history for recovery, drop old versions so the bucket stays small.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  for_each = aws_s3_bucket.state

  bucket = each.value.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days           = 30
      newer_noncurrent_versions = 10
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]
}

data "aws_iam_policy_document" "state_tls" {
  for_each = aws_s3_bucket.state

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]

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

resource "aws_s3_bucket_policy" "state" {
  for_each = aws_s3_bucket.state

  bucket = each.value.id
  policy = data.aws_iam_policy_document.state_tls[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.state]
}
