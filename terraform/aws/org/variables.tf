variable "region" {
  description = "Home region: the trail's bucket, log group and metrics live here."
  type        = string
  default     = "us-east-1"
}

variable "log_retention_days" {
  description = "Days the trail's CloudWatch log group keeps events. The S3 copy is kept for bucket_retention_days."
  type        = number
  default     = 90
}

variable "bucket_retention_days" {
  description = "Days the trail's S3 bucket keeps log files."
  type        = number
  default     = 365
}

variable "metric_namespace" {
  description = "CloudWatch namespace of the audit metrics the alert job reads."
  type        = string
  default     = "PlatformAudit"
}

variable "github_repo" {
  description = "Repository name, for the repo tag."
  type        = string
  default     = "slack-script"
}
