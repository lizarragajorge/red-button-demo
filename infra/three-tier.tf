variable "activate_queued_execution" {
  description = "Activate the queued web runtime and worker after provisioning. False pauses the worker and keeps the web app synchronous without deleting durable storage."
  type        = bool
  default     = true
}

locals {
  commvault_url   = var.existing_apim_base_url != "" ? var.existing_apim_base_url : var.commvault_base_url
  work_containers = toset(["requests", "inventory", "coordination", "stub-state"])
  work_queues     = toset(["requests", "requests-poison"])
  web_blob_roles = {
    requests  = "Storage Blob Data Contributor"
    inventory = "Storage Blob Data Reader"
  }
}

resource "azurerm_storage_account" "three_tier" {
  for_each = var.enable_three_tier ? toset(["work", "host"]) : toset([])

  name                            = "rb${each.key}${substr(sha256("${var.subscription_id}/${var.app_name}"), 0, 16)}"
  resource_group_name             = azurerm_resource_group.demo.name
  location                        = azurerm_service_plan.demo.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  public_network_access           = var.enable_private_storage_networking ? "Disabled" : "Enabled"
  tags                            = local.tags
}

# AzureRM 5 uses ARM resource IDs for these resources, not storage data-plane keys.
resource "azurerm_storage_container" "work" {
  for_each              = var.enable_three_tier ? local.work_containers : toset([])
  name                  = each.key
  storage_account_id    = azurerm_storage_account.three_tier["work"].id
  container_access_type = "private"
}

resource "azurerm_storage_queue" "work" {
  for_each           = var.enable_three_tier ? local.work_queues : toset([])
  name               = each.key
  storage_account_id = azurerm_storage_account.three_tier["work"].id
}

resource "azurerm_role_assignment" "web_blobs" {
  for_each             = var.enable_three_tier ? local.web_blob_roles : {}
  scope                = azurerm_storage_container.work[each.key].id
  role_definition_name = each.value
  principal_id         = azurerm_linux_web_app.demo.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "web_queue" {
  count                = var.enable_three_tier ? 1 : 0
  scope                = azurerm_storage_queue.work["requests"].id
  role_definition_name = "Storage Queue Data Message Sender"
  principal_id         = azurerm_linux_web_app.demo.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_linux_function_app" "worker" {
  count                                          = var.enable_three_tier ? 1 : 0
  enabled                                        = var.activate_queued_execution
  name                                           = "${var.app_name}-worker"
  resource_group_name                            = azurerm_resource_group.demo.name
  location                                       = azurerm_service_plan.demo.location
  service_plan_id                                = azurerm_service_plan.demo.id
  storage_account_name                           = azurerm_storage_account.three_tier["host"].name
  storage_uses_managed_identity                  = true
  functions_extension_version                    = "~4"
  https_only                                     = true
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  builtin_logging_enabled                        = false
  virtual_network_subnet_id                      = var.enable_private_storage_networking ? azurerm_subnet.storage_integration[0].id : null
  tags                                           = local.tags

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on                              = true
    minimum_tls_version                    = "1.2"
    scm_minimum_tls_version                = "1.2"
    ftps_state                             = "Disabled"
    application_insights_connection_string = azurerm_application_insights.demo.connection_string
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = merge({
    APP_ENV                         = "production"
    PUBLIC_ORIGIN                   = local.app_url
    ENTRA_TENANT_ID                 = data.azurerm_client_config.current.tenant_id
    ENTRA_API_CLIENT_ID             = azuread_application.api.client_id
    ENTRA_SPA_CLIENT_ID             = azuread_application.spa.client_id
    EXECUTION_MODE                  = "queued"
    STORAGE_ACCOUNT_NAME            = azurerm_storage_account.three_tier["work"].name
    WORK_STORAGE__queueServiceUri   = azurerm_storage_account.three_tier["work"].primary_queue_endpoint
    WORK_STORAGE__credential        = "managedidentity"
    AzureWebJobsStorage__credential = "managedidentity"
    FUNCTIONS_WORKER_RUNTIME        = "python"
    INVENTORY_REFRESH_SCHEDULE      = "0 */5 * * * *"
    INVENTORY_MAX_AGE_SECONDS       = "900"
    COMMVAULT_MODE                  = var.commvault_mode
    COMMVAULT_BASE_URL              = local.commvault_url
    COMMVAULT_AUTH_HEADER           = var.commvault_auth_header
    ENABLE_LIVE_OPERATIONS          = tostring(var.enable_live_operations)
    SCM_DO_BUILD_DURING_DEPLOYMENT  = "false"
    ENABLE_ORYX_BUILD               = "false"
    }, var.commvault_mode == "live" ? {
    COMMVAULT_AUTH_VALUE = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.demo.vault_uri}secrets/${var.commvault_secret_name}/)"
  } : {})
}

resource "azurerm_role_assignment" "worker_blobs" {
  for_each             = var.enable_three_tier ? local.work_containers : toset([])
  scope                = azurerm_storage_container.work[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_function_app.worker[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# Both triggers dequeue/update/delete; the main trigger also sends poison messages.
resource "azurerm_role_assignment" "worker_queues" {
  for_each             = var.enable_three_tier ? local.work_queues : toset([])
  scope                = azurerm_storage_queue.work[each.key].id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_linux_function_app.worker[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# Host leases/receipts require account scope; isolate them from application data.
resource "azurerm_role_assignment" "worker_host" {
  for_each = var.enable_three_tier ? toset([
    "Storage Blob Data Owner", "Storage Queue Data Contributor"
  ]) : toset([])
  scope                = azurerm_storage_account.three_tier["host"].id
  role_definition_name = each.key
  principal_id         = azurerm_linux_function_app.worker[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "worker_secrets" {
  count                = var.enable_three_tier && var.commvault_mode == "live" ? 1 : 0
  scope                = azurerm_key_vault.demo.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_function_app.worker[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"
}
