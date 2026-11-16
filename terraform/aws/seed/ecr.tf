# The Lambda's container image. It lives here, not in DEV, because a Lambda cannot be created
# until its image exists, so the repository has to outlive and precede the function. The
# deploy-aws-dev workflow pushes to it, and DEV points the function at it.
# Tags are mutable on purpose: the function is first created from the latest tag, before any deploy
# has run. Only the deployer and the seed admin can push, and each deploy also tags by commit.
#trivy:ignore:AWS-0031
#trivy:ignore:AWS-0033
resource "aws_ecr_repository" "app" {
  # checkov:skip=CKV_AWS_51: the deploy workflow moves the latest tag, so tags must be mutable
  # checkov:skip=CKV_AWS_136: AWS-managed encryption (AES256) is enough for an image with no secrets in it
  name                 = "anomaly-alerts"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Keep a few images for a rollback, and drop the rest so the bill stays at pennies.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Drop untagged images after a day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the last 5 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = { type = "expire" }
      },
    ]
  })
}

# Lets the Lambda service pull the image for functions in this account.
data "aws_iam_policy_document" "ecr_lambda_pull" {
  statement {
    sid     = "LambdaPull"
    actions = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "aws:sourceArn"
      values   = ["arn:aws:lambda:${var.region}:${data.aws_caller_identity.current.account_id}:function:*"]
    }
  }
}

resource "aws_ecr_repository_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy     = data.aws_iam_policy_document.ecr_lambda_pull.json
}
