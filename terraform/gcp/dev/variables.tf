variable "project_id" {
  description = "Project that runs the jobs. Its metrics scope covers the org (terraform/gcp/org)."
  type        = string
  default     = "slack-anomaly-dev"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "time_zone" {
  description = "Time zone for the routine report schedules."
  type        = string
  default     = "America/New_York"
}

variable "slack_channel_id" {
  description = "Slack channel the routine reports share one message in (the channel ID, not its name)."
  type        = string
  default     = "C0CC5RTC4R0"
}

variable "billing_table" {
  description = "Cloud Billing export table read by the cost report. The billing account's Standard export already goes to shiptrack; terraform/gcp/org grants read access to it."
  type        = string
  default     = "tensile-runway-511902-q9.shiptrack_billing_export.gcp_billing_export_v1_01B37B_E44281_12EC5F"
}

variable "second_billing_table" {
  description = "Cloud Billing export table of the second billing account (My Billing Account), which pays for projects in the skills project's account. terraform/gcp/org grants read access to it."
  type        = string
  default     = "skills-mjl-27850.billing_export.gcp_billing_export_v1_0197A6_C9B1CC_56B1EE"
}
