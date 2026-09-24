resource "azurerm_resource_group" "demo" {
  name     = "${var.app_name}-rg"
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "demo" {
  name                = "${var.app_name}-logs"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
  tags                = local.tags
}

resource "azurerm_application_insights" "demo" {
  name                = "${var.app_name}-insights"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  workspace_id        = azurerm_log_analytics_workspace.demo.id
  application_type    = "web"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_key_vault" "demo" {
  name                          = "kv-${substr(replace(var.app_name, "-", ""), 0, 12)}-${substr(sha256("${var.subscription_id}/${var.app_name}"), 0, 8)}"
  location                      = azurerm_resource_group.demo.location
  resource_group_name           = azurerm_resource_group.demo.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  public_network_access_enabled = var.key_vault_public_network_access_enabled
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  tags                          = local.tags
}

resource "azurerm_service_plan" "demo" {
  name                = "${var.app_name}-plan"
  location            = coalesce(var.app_service_location, azurerm_resource_group.demo.location)
  resource_group_name = azurerm_resource_group.demo.name
  os_type             = "Linux"
  sku_name            = var.service_plan_sku
  tags                = local.tags
}

resource "azurerm_linux_web_app" "demo" {
  virtual_network_subnet_id                      = var.enable_private_storage_networking ? azurerm_subnet.storage_integration[0].id : null
  depends_on                                     = [azurerm_application_gateway.ingress]
  name                                           = var.app_name
  location                                       = azurerm_service_plan.demo.location
  resource_group_name                            = azurerm_resource_group.demo.name
  service_plan_id                                = azurerm_service_plan.demo.id
  https_only                                     = true
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  tags                                           = local.tags

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on                         = true
    minimum_tls_version               = "1.2"
    scm_minimum_tls_version           = "1.2"
    ftps_state                        = "Disabled"
    http2_enabled                     = true
    app_command_line                  = "python -m server"
    ip_restriction_default_action     = var.enable_gateway_ingress ? "Deny" : "Allow"
    scm_use_main_ip_restriction       = false
    scm_ip_restriction_default_action = var.enable_gateway_ingress ? "Deny" : "Allow"

    dynamic "scm_ip_restriction" {
      for_each = var.enable_gateway_ingress ? var.gateway_scm_allowed_cidrs : toset([])
      content {
        name       = "ApprovedDeployment-${replace(scm_ip_restriction.value, "/", "-")}"
        priority   = 100
        action     = "Allow"
        ip_address = scm_ip_restriction.value
      }
    }

    dynamic "ip_restriction" {
      for_each = var.enable_gateway_ingress ? [1] : []
      content {
        name                      = "ApplicationGatewaySubnet"
        priority                  = 100
        action                    = "Allow"
        virtual_network_subnet_id = azurerm_subnet.gateway[0].id
      }
    }

    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = merge({
    APP_ENV                               = "production"
    WEB_CONCURRENCY                       = "1"
    PORT                                  = "8080"
    PYTHONPATH                            = "/home/site/wwwroot/.python_packages/lib/site-packages"
    ENTRA_TENANT_ID                       = data.azurerm_client_config.current.tenant_id
    ENTRA_API_CLIENT_ID                   = azuread_application.api.client_id
    ENTRA_SPA_CLIENT_ID                   = azuread_application.spa.client_id
    PUBLIC_ORIGIN                         = local.app_url
    APP_DISPLAY_NAME                      = trimspace(var.display_name)
    SUPPORT_URL                           = var.support_url
    COMMVAULT_MODE                        = var.commvault_mode
    COMMVAULT_BASE_URL                    = local.commvault_url
    COMMVAULT_AUTH_HEADER                 = var.commvault_auth_header
    ENABLE_LIVE_OPERATIONS                = tostring(var.enable_live_operations)
    SCM_DO_BUILD_DURING_DEPLOYMENT        = "false"
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.demo.connection_string
    }, var.commvault_mode == "live" ? {
    COMMVAULT_AUTH_VALUE = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.demo.vault_uri}secrets/${var.commvault_secret_name}/)"
    } : {}, var.enable_three_tier ? {
    EXECUTION_MODE       = var.activate_queued_execution ? "queued" : "sync"
    STORAGE_ACCOUNT_NAME = azurerm_storage_account.three_tier["work"].name
  } : {})

  logs {
    application_logs {
      file_system_level = "Information"
    }
    http_logs {
      file_system {
        retention_in_days = 3
        retention_in_mb   = 35
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.commvault_mode != "live" || local.commvault_url != ""
      error_message = "Live mode requires commvault_base_url including its API path prefix."
    }
    precondition {
      condition     = !var.enable_live_operations || var.commvault_mode == "live"
      error_message = "enable_live_operations may only be enabled in live mode."
    }
  }
}

resource "azurerm_role_assignment" "web_app_secrets" {
  scope                = azurerm_key_vault.demo.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_web_app.demo.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_monitor_diagnostic_setting" "web_app" {
  name                       = "workspace"
  target_resource_id         = azurerm_linux_web_app.demo.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.demo.id

  dynamic "enabled_log" {
    for_each = toset(["AppServiceHTTPLogs", "AppServiceConsoleLogs", "AppServiceAppLogs", "AppServicePlatformLogs"])
    content {
      category = enabled_log.value
    }
  }

  enabled_metric {
    category = "AllMetrics"
  }
}

resource "azurerm_monitor_diagnostic_setting" "key_vault" {
  name                       = "workspace"
  target_resource_id         = azurerm_key_vault.demo.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.demo.id

  enabled_log {
    category = "AuditEvent"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
