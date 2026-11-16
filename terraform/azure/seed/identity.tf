# Keyless access for GitHub Actions. Azure attaches roles to a principal, so each
# identity is its own app registration (the names match the other clouds), and each
# trusts only the GitHub environments that should be able to use it.
locals {
  github_subjects = {
    seed = "${local.subject_prefix}:environment:SEED"
    dev  = "${local.subject_prefix}:environment:DEV"
    ci   = "${local.subject_prefix}:environment:CI"
  }

  # SEED applies the seed, DEV applies dev, and CI plans (read-only) and destroys dev.
  identity_subjects = {
    seed-admin   = { seed = local.github_subjects.seed }
    dev-deployer = { dev = local.github_subjects.dev, ci = local.github_subjects.ci }
    tf-planner   = { ci = local.github_subjects.ci }
  }

  federated_credentials = merge([
    for identity, subjects in local.identity_subjects : {
      for env, subject in subjects : "${identity}-${env}" => {
        identity = identity
        env      = env
        subject  = subject
      }
    }
  ]...)
}

resource "azuread_application" "github" {
  for_each = local.identity_subjects

  display_name = "${var.name_prefix}-${each.key}"
  owners       = [data.azuread_client_config.current.object_id]
  # App registrations have no key-value tags, only labels, so the same set is written as key:value.
  tags = sort([for key, value in local.tags : "${key}:${value}"])

  dynamic "required_resource_access" {
    # The planner reads this directory's apps to plan the seed, so it needs Graph read.
    for_each = each.key == "tf-planner" ? [1] : []
    content {
      resource_app_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]

      resource_access {
        id   = data.azuread_service_principal.msgraph.app_role_ids["Application.Read.All"]
        type = "Role"
      }
    }
  }
}

resource "azuread_service_principal" "github" {
  for_each = azuread_application.github

  client_id = each.value.client_id
  owners    = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_federated_identity_credential" "github" {
  # checkov:skip=CKV_AZURE_249: each subject pins the immutable repository and owner IDs and one GitHub environment, which the check's name-based pattern does not recognise
  for_each = local.federated_credentials

  application_id = azuread_application.github[each.value.identity].id
  display_name   = each.key
  description    = "GitHub Actions, ${var.github_owner}/${var.github_repo}, environment ${upper(each.value.env)}"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = each.value.subject
}

data "azuread_application_published_app_ids" "well_known" {}

# Microsoft's own Graph service principal. Read only: managing it would let a destroy delete it.
data "azuread_service_principal" "msgraph" {
  client_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
}

resource "azuread_app_role_assignment" "planner_reads_directory" {
  app_role_id         = data.azuread_service_principal.msgraph.app_role_ids["Application.Read.All"]
  principal_object_id = azuread_service_principal.github["tf-planner"].object_id
  resource_object_id  = data.azuread_service_principal.msgraph.object_id
}
