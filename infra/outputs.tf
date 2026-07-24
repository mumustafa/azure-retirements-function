output "function_app_url" {
  description = "Default HTTPS URL of the deployed Function App."
  value       = "https://${azurerm_linux_function_app.func.default_hostname}"
}

output "function_app_name" {
  description = "Name of the Function App."
  value       = azurerm_linux_function_app.func.name
}

output "resource_group_name" {
  description = "Name of the resource group."
  value       = azurerm_resource_group.rg.name
}

output "managed_identity_principal_id" {
  description = "Principal ID of the Function App's system-assigned managed identity (useful for additional manual role assignments)."
  value       = azurerm_linux_function_app.func.identity[0].principal_id
}

output "application_insights_connection_string" {
  description = "Application Insights connection string."
  value       = azurerm_application_insights.ai.connection_string
  sensitive   = true
}
