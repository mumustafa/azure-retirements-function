# B1 App Service plan (Linux, dedicated)
resource "azurerm_service_plan" "plan" {
  name                = "${var.function_app_name}-plan"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "B1"

  tags = var.tags
}

resource "azurerm_linux_web_app" "app" {
  name                = var.function_app_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_service_plan.plan.id

  # System-assigned identity used by DefaultAzureCredential for Resource Graph.
  identity {
    type = "SystemAssigned"
  }

  # Disable legacy publish paths.
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false

  site_config {
    application_stack {
      python_version = var.python_version
    }

    # Oryx builds the venv during zip deploy; gunicorn runs the FastAPI app.
    app_command_line = "gunicorn -w 2 -k uvicorn.workers.UvicornWorker --timeout 600 app:app"
  }

  app_settings = {
    SCM_DO_BUILD_DURING_DEPLOYMENT        = "true"
    ENABLE_ORYX_BUILD                     = "true"
    AZURE_SUBSCRIPTION_IDS                = join(",", var.azure_subscription_ids)
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.ai.connection_string
  }

  tags = var.tags
}

# Reader on every monitored subscription — required for Resource Graph queries.
resource "azurerm_role_assignment" "app_reader" {
  for_each = toset(var.azure_subscription_ids)

  principal_id         = azurerm_linux_web_app.app.identity[0].principal_id
  role_definition_name = "Reader"
  scope                = "/subscriptions/${each.value}"
}

