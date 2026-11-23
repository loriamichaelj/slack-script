output "workspace" {
  description = "Workspace that receives the Activity Log. The alert job reads it through its subscription-wide Monitoring Reader role."
  value       = azurerm_log_analytics_workspace.audit.name
}
