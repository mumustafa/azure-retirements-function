terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # Uncomment and configure to store state remotely (recommended for production).
  # backend "azurerm" {
  #   resource_group_name  = "tfstate-rg"
  #   storage_account_name = "tfstateXXXXXXXX"
  #   container_name       = "tfstate"
  #   key                  = "azure-retirement-navigator.terraform.tfstate"
  # }
}

provider "azurerm" {
  features {}
  # Use Entra ID (Azure AD) for all storage data-plane calls.
  # Required when key-based authentication is disabled by policy.
  storage_use_azuread = true
}

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location

  tags = var.tags
}
