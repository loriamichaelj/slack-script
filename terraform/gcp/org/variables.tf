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

variable "billing_dataset" {
  description = "Dataset holding the billing account's Standard usage cost export, as project.dataset."
  type        = string
  default     = "tensile-runway-511902-q9.shiptrack_billing_export"
}

variable "exclude_projects" {
  description = "Project IDs to leave out of the metrics scope."
  type        = list(string)
  default     = []
}
