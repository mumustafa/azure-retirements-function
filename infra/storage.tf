resource "azurerm_storage_account" "func_storage" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  # Reflects the tenant policy — key-based auth is not permitted.
  shared_access_key_enabled = false

  tags = var.tags
}

# Private container for deployment packages (WEBSITE_RUN_FROM_PACKAGE).
# The function app reads from this container using its managed identity.
resource "azurerm_storage_container" "deployments" {
  name                  = "deployments"
  storage_account_id    = azurerm_storage_account.func_storage.id
  container_access_type = "private"
}
