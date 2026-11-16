variable "name_prefix" {
  description = "Prefix for state buckets and other global names."
  type        = string
  default     = "slack-anomaly-dev"
}

variable "region" {
  type    = string
  default = "us-east-1"
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

variable "tags" {
  description = "Extra tags merged into the defaults applied to every resource."
  type        = map(string)
  default     = {}
}
