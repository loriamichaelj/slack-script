output "trail" {
  description = "The account's multi-region trail."
  value       = aws_cloudtrail.platform.arn
}

output "audit_metrics" {
  description = "CloudWatch metrics the alert job reads, in the metric_namespace namespace."
  value       = sort(keys(aws_cloudwatch_log_metric_filter.audit))
}
