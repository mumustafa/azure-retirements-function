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
  description = "Name of the Azure Function App. Must be globally unique."
  type        = string
}

variable "storage_account_name" {
  description = "Name of the storage account used by the Functions runtime. Must be globally unique, 3–24 lowercase alphanumeric characters."
  type        = string
}

variable "azure_subscription_ids" {
  description = "List of Azure subscription IDs to query for retirement data. The Function App's managed identity is granted Reader on each."
  type        = list(string)
}

variable "python_version" {
  description = "Python runtime version for the Function App."
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
