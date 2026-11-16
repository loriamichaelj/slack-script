output "jobs" {
  description = "Container Apps jobs and their cron schedules (UTC)."
  value       = { for name, j in local.jobs : name => j.schedule }
}

output "resource_group" {
  value = local.rg
}

output "app_account" {
  description = "Storage account with the cooldown state at app/state/alerts.json."
  value       = azurerm_storage_account.app.name
}
