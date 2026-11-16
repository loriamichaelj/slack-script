output "github_oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}

output "seed_admin_role_arn" {
  description = "AWS_ROLE_ARN for the SEED GitHub environment."
  value       = aws_iam_role.github["seed-admin"].arn
}

output "dev_deployer_role_arn" {
  description = "AWS_ROLE_ARN for the DEV and CI GitHub environments (apply, destroy)."
  value       = aws_iam_role.github["dev-deployer"].arn
}

output "tf_planner_role_arn" {
  description = "AWS_PLAN_ROLE_ARN for the CI GitHub environment (plan)."
  value       = aws_iam_role.github["tf-planner"].arn
}

output "runtime_role_arn" {
  description = "Execution role for the Lambda functions."
  value       = aws_iam_role.runtime.arn
}

output "state_buckets" {
  value = { for k, b in aws_s3_bucket.state : k => b.bucket }
}

output "webhook_secret_arns" {
  value = { for k, s in aws_secretsmanager_secret.webhook : k => s.arn }
}
