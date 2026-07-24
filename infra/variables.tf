variable "resource_group_name" {
  description = "Name of the Azure resource group that will contain all resources."
  type        = string
  default     = "azure-retirement-navigator-rg"
}

variable "location" {
  description = "Azure region for all resources (e.g. 'eastus', 'westeurope')."
  type        = string
  default     = "eastus"
}

variable "function_app_name" {
  description = "Name of the App Service. Must be globally unique (used as the azurewebsites.net hostname)."
  type        = string
}

variable "azure_subscription_ids" {
  description = "List of Azure subscription IDs to query for retirement data. The App Service's managed identity is granted Reader on each."
  type        = list(string)
}

variable "python_version" {
  description = "Python runtime version for the App Service."
  type        = string
  default     = "3.11"
}

variable "log_retention_days" {
  description = "Retention period in days for the Log Analytics workspace."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}

