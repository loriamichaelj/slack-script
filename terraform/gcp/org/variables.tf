variable "org_id" {
  description = "Organization whose projects are added to the metrics scope."
  type        = string
  default     = "618554946741"
}

variable "project_id" {
  description = "Scoping project: the job reads every org project's metrics through it."
  type        = string
  default     = "slack-anomaly-dev"
}

variable "billing_datasets" {
  description = "Datasets holding each billing account's Standard usage cost export, as project.dataset."
  type        = list(string)
  default = [
    "tensile-runway-511902-q9.shiptrack_billing_export", # Organization Billing
    "skills-mjl-27850.billing_export",                   # My Billing Account
  ]
}

variable "uptime_hosts" {
  description = "Public sites to check over HTTPS from outside, as short name => host. Each check fetches / every 5 minutes from 3 regions."
  type        = map(string)
  default = {
    "michaeljloria-com" = "michaeljloria.com"
  }
}

variable "log_retention_days" {
  description = "Days the org log bucket keeps entries."
  type        = number
  default     = 30
}

variable "exclude_projects" {
  description = "Project IDs to leave out of the metrics scope."
  type        = list(string)
  default     = []
}
