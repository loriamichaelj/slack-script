output "function_name" {
  description = "The Lambda that deploy-aws-dev uploads code to."
  value       = aws_lambda_function.app.function_name
}

output "app_bucket" {
  description = "Bucket with config.yaml and state/alerts.json."
  value       = aws_s3_bucket.app.id
}

output "jobs" {
  description = "Schedules and their cron expressions."
  value       = { for name, j in local.jobs : name => j.schedule }
}
