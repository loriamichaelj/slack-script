variable "name_prefix" {
  description = "Prefix for global names. Must match SEED, which grants the runtime role access to <prefix>-anomaly-app."
  type        = string
  default     = "slack-anomaly-dev"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "time_zone" {
  description = "Time zone for the routine report schedules."
  type        = string
  default     = "America/New_York"
}

variable "log_retention_days" {
  description = "How long the Lambda's logs are kept."
  type        = number
  default     = 14
}
