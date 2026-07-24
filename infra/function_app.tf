# User-assigned identity for the Functions storage connection.
# Created before the Function App so role assignments can be applied first,
# avoiding the circular dependency that system-assigned identity creates
# when key-based storage auth is disabled by policy.
resource "azurerm_user_assigned_identity" "func_storage_id" {
  name                = "${var.function_app_name}-storage-id"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location

  tags = var.tags
}

# Storage role assignments — must exist before the Function App is created.
resource "azurerm_role_assignment" "func_storage_blob_owner" {
  principal_id         = azurerm_user_assigned_identity.func_storage_id.principal_id
  role_definition_name = "Storage Blob Data Owner"
  scope                = azurerm_storage_account.func_storage.id
}

resource "azurerm_role_assignment" "func_storage_queue_contributor" {
  principal_id         = azurerm_user_assigned_identity.func_storage_id.principal_id
  role_definition_name = "Storage Queue Data Contributor"
  scope                = azurerm_storage_account.func_storage.id
}

resource "azurerm_role_assignment" "func_storage_table_contributor" {
  principal_id         = azurerm_user_assigned_identity.func_storage_id.principal_id
  role_definition_name = "Storage Table Data Contributor"
  scope                = azurerm_storage_account.func_storage.id
}

# Serverless Consumption plan (Linux, Y1)
resource "azurerm_service_plan" "plan" {
  name                = "${var.function_app_name}-plan"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "Y1"

  tags = var.tags
}

resource "azurerm_linux_function_app" "func" {
  name                = var.function_app_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_service_plan.plan.id

  storage_account_name          = azurerm_storage_account.func_storage.name
  storage_uses_managed_identity = true

  # SystemAssigned  — used by DefaultAzureCredential for Resource Graph queries.
  # UserAssigned    — used by the Functions runtime for key-less storage access.
  identity {
    type         = "SystemAssigned, UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.func_storage_id.id]
  }

  # Ensure role assignments exist before the app tries to connect to storage.
  depends_on = [
    azurerm_role_assignment.func_storage_blob_owner,
    azurerm_role_assignment.func_storage_queue_contributor,
    azurerm_role_assignment.func_storage_table_contributor,
  ]

  # Disable all basic-auth publish paths (policy requirement).
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false

  site_config {
    application_stack {
      python_version = var.python_version
    }

    # Allow the static SPA to call the same-origin /api endpoints.
    cors {
      allowed_origins = ["https://${var.function_app_name}.azurewebsites.net"]
    }
  }

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME              = "python"
    AZURE_SUBSCRIPTION_IDS                = join(",", var.azure_subscription_ids)
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.ai.connection_string
    # Oryx remote build: Kudu installs Python packages server-side from
    # requirements.txt, bypassing the tenant policy that blocks public network
    # access on the storage account. No WEBSITE_RUN_FROM_PACKAGE needed —
    # files are deployed to /home/site/wwwroot via /api/zipdeploy.
    ENABLE_ORYX_BUILD                     = "true"
    SCM_DO_BUILD_DURING_DEPLOYMENT        = "true"
  }

  tags = var.tags
}

# Grant the Function App's system-assigned identity Storage Blob Data Owner so
# the Kudu/SCM build container can upload the squashfs deployment artifact.
# (The user-assigned identity covers runtime storage; this covers deployment.)
resource "azurerm_role_assignment" "func_system_storage_blob_owner" {
  principal_id         = azurerm_linux_function_app.func.identity[0].principal_id
  role_definition_name = "Storage Blob Data Owner"
  scope                = azurerm_storage_account.func_storage.id
}

# Grant the Function App's managed identity Reader access on every
# monitored subscription so that Resource Graph queries succeed.
resource "azurerm_role_assignment" "func_reader" {
  for_each = toset(var.azure_subscription_ids)

  principal_id         = azurerm_linux_function_app.func.identity[0].principal_id
  role_definition_name = "Reader"
  scope                = "/subscriptions/${each.value}"
}
