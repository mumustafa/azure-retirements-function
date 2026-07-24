output "app_url" {
  description = "Default HTTPS URL of the deployed App Service."
  value       = "https://${azurerm_linux_web_app.app.default_hostname}"
}

output "app_name" {
  description = "Name of the App Service."
  value       = azurerm_linux_web_app.app.name
}

output "resource_group_name" {
  description = "Name of the resource group."
  value       = azurerm_resource_group.rg.name
}

output "managed_identity_principal_id" {
  description = "Principal ID of the App Service's system-assigned managed identity (useful for additional manual role assignments)."
  value       = azurerm_linux_web_app.app.identity[0].principal_id
}

output "application_insights_connection_string" {
  description = "Application Insights connection string."
  value       = azurerm_application_insights.ai.connection_string
  sensitive   = true
}

