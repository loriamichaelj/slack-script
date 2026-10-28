variable "project_id" {
  description = "Project that holds the SEED and DEV resources."
  type        = string
  default     = "slack-anomaly-dev"
}

variable "region" {
  description = "Region for the state buckets, and later the Cloud Run job."
  type        = string
  default     = "us-central1"
}

variable "github_owner" {
  type    = string
  default = "loriamichaelj"
}

variable "github_repo" {
  type    = string
  default = "slack-script"
}

# GitHub's immutable subject claim embeds these IDs, and trusting the IDs
# stops a deleted and re-created repo of the same name from impersonating this one.
variable "github_owner_id" {
  type    = string
  default = "165821667"
}

variable "github_repo_id" {
  type    = string
  default = "1437191668"
}

variable "labels" {
  description = "Extra labels merged into the defaults applied to every resource."
  type        = map(string)
  default     = {}
}
