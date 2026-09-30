mock_provider "azurerm" {
  override_during = plan

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "11111111-1111-1111-1111-111111111111"
      object_id       = "22222222-2222-2222-2222-222222222222"
      subscription_id = "33333333-3333-3333-3333-333333333333"
    }
  }

  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.OperationalInsights/workspaces/test-logs"
    }
  }

  mock_resource "azurerm_service_plan" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Web/serverFarms/test-plan"
    }
  }

  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.KeyVault/vaults/test-vault"
      vault_uri = "https://test-vault.vault.azure.net/"
    }
  }

  mock_resource "azurerm_linux_web_app" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Web/sites/test-app"
      identity = {
        type         = "SystemAssigned"
        principal_id = "44444444-4444-4444-4444-444444444444"
        tenant_id    = "11111111-1111-1111-1111-111111111111"
      }
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id                     = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Storage/storageAccounts/teststorage"
      primary_queue_endpoint = "https://teststorage.queue.core.windows.net/"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Storage/storageAccounts/teststorage/blobServices/default/containers/test-container"
    }
  }
  mock_resource "azurerm_storage_queue" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Storage/storageAccounts/teststorage/queueServices/default/queues/test-queue"
    }
  }
  mock_resource "azurerm_linux_function_app" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Web/sites/test-worker"
      identity = {
        type         = "SystemAssigned"
        principal_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        tenant_id    = "11111111-1111-1111-1111-111111111111"
      }
    }
  }
  mock_resource "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Network/virtualNetworks/test-vnet/subnets/gateway"
    }
  }
  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Network/virtualNetworks/test-vnet"
    }
  }
  mock_resource "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    }
  }
  mock_resource "azurerm_network_security_group" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Network/networkSecurityGroups/test-nsg"
    }
  }
  mock_resource "azurerm_public_ip" {
    defaults = {
      id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.Network/publicIPAddresses/test-ip"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/test-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-gateway"
      principal_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    }
  }
}

mock_provider "azuread" {
  override_during = plan

  mock_resource "azuread_service_principal" {
    defaults = {
      object_id = "55555555-5555-5555-5555-555555555555"
    }
  }
}

override_resource {
  target          = azuread_application.api
  override_during = plan
  values = {
    id        = "/applications/66666666-6666-6666-6666-666666666666"
    client_id = "77777777-7777-7777-7777-777777777777"
  }
}

override_resource {
  target          = azuread_application.spa
  override_during = plan
  values = {
    id        = "/applications/88888888-8888-8888-8888-888888888888"
    client_id = "99999999-9999-9999-9999-999999999999"
  }
}

variables {
  subscription_id                         = "33333333-3333-3333-3333-333333333333"
  app_name                                = "red-button-local-test"
  app_service_location                    = null
  operator_object_ids                     = []
  api_assignment_required                 = null
  allow_signed_in_demo_operations         = true
  spa_assignment_required                 = false
  enable_multi_tenant                     = false
  allowed_tenant_ids                      = []
  commvault_mode                          = "stub"
  enable_live_operations                  = false
  key_vault_public_network_access_enabled = true
  enable_private_storage_networking       = false
  enable_gateway_ingress                  = false
  existing_apim_base_url                  = ""
}

run "secure_stub_defaults" {
  command = plan

  assert {
    condition = (
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_MODE"] == "stub" &&
      azurerm_linux_web_app.demo.app_settings["APP_DISPLAY_NAME"] == "Red Button" &&
      azurerm_linux_web_app.demo.app_settings["SUPPORT_URL"] == "" &&
      azurerm_linux_web_app.demo.app_settings["ENABLE_LIVE_OPERATIONS"] == "false" &&
      azurerm_linux_web_app.demo.app_settings["ALLOW_SIGNED_IN_DEMO_OPERATIONS"] == "true" &&
      !contains(keys(azurerm_linux_web_app.demo.app_settings), "COMMVAULT_AUTH_VALUE") &&
      azurerm_linux_web_app.demo.app_settings["PORT"] == "8080" &&
      !contains(keys(azurerm_linux_web_app.demo.app_settings), "NODE_ENV") &&
      azurerm_linux_web_app.demo.app_settings["APP_ENV"] == "production" &&
      azurerm_linux_web_app.demo.app_settings["WEB_CONCURRENCY"] == "1" &&
      azurerm_linux_web_app.demo.app_settings["PYTHONPATH"] == "/home/site/wwwroot/.python_packages/lib/site-packages" &&
      azurerm_linux_web_app.demo.app_settings["SCM_DO_BUILD_DURING_DEPLOYMENT"] == "false" &&
      !contains(keys(azurerm_linux_web_app.demo.app_settings), "NPM_CONFIG_PRODUCTION") &&
      azurerm_linux_web_app.demo.app_settings["ENTRA_API_CLIENT_ID"] == azuread_application.api.client_id &&
      azurerm_linux_web_app.demo.app_settings["ENTRA_TENANT_ID"] == data.azurerm_client_config.current.tenant_id &&
      !contains(keys(azurerm_linux_web_app.demo.app_settings), "ENTRA_MULTI_TENANT") &&
      !contains(keys(azurerm_linux_web_app.demo.app_settings), "ENTRA_ALLOWED_TENANT_IDS") &&
      azurerm_linux_web_app.demo.app_settings["PUBLIC_ORIGIN"] == output.app_url
    )
    error_message = "Default app settings must match the backend contract without live credentials."
  }

  assert {
    condition = (
      azurerm_linux_web_app.demo.https_only &&
      azurerm_linux_web_app.demo.site_config[0].minimum_tls_version == "1.2" &&
      azurerm_linux_web_app.demo.site_config[0].scm_minimum_tls_version == "1.2" &&
      azurerm_linux_web_app.demo.site_config[0].ftps_state == "Disabled" &&
      !azurerm_linux_web_app.demo.ftp_publish_basic_authentication_enabled &&
      !azurerm_linux_web_app.demo.webdeploy_publish_basic_authentication_enabled &&
      azurerm_linux_web_app.demo.site_config[0].application_stack[0].python_version == "3.12" &&
      (azurerm_linux_web_app.demo.site_config[0].application_stack[0].node_version == null ||
      azurerm_linux_web_app.demo.site_config[0].application_stack[0].node_version == "") &&
      azurerm_linux_web_app.demo.site_config[0].app_command_line == "python -m server" &&
      azurerm_service_plan.demo.sku_name == "B1" &&
      azurerm_key_vault.demo.rbac_authorization_enabled &&
      azurerm_key_vault.demo.purge_protection_enabled
    )
    error_message = "Hosting must retain secure defaults and run Python 3.12 through the canonical server module."
  }

  assert {
    condition = (
      !azuread_service_principal.api.app_role_assignment_required &&
      !azuread_service_principal.spa.app_role_assignment_required &&
      length(azuread_app_role_assignment.operator) == 0 &&
      azuread_application.api.sign_in_audience == "AzureADMyOrg" &&
      azuread_application.spa.sign_in_audience == "AzureADMyOrg" &&
      azuread_application_identifier_uri.api.identifier_uri == "api://${azuread_application.api.client_id}" &&
      azuread_application.api.api[0].requested_access_token_version == 2 &&
      one(azuread_application.api.app_role).value == "BackupOperator" &&
      one(azuread_application.api.app_role).allowed_member_types == toset(["User"]) &&
      azuread_application.spa.single_page_application[0].redirect_uris == toset([
        "https://red-button-local-test.azurewebsites.net/", "https://red-button-local-test.azurewebsites.net/auth/silent",
        "http://localhost:5173/", "http://localhost:5173/auth/silent",
        "http://localhost:8080/", "http://localhost:8080/auth/silent",
      ]) &&
      azuread_application_pre_authorized.spa.permission_ids == toset([local.scope_id])
    )
    error_message = "Identity must enforce the delegated v2 token and operator role contract."
  }

  assert {
    condition = (
      length(azurerm_monitor_diagnostic_setting.web_app.enabled_log) == 4 &&
      azurerm_application_insights.demo.application_type == "web" &&
      one(azurerm_monitor_diagnostic_setting.key_vault.enabled_log).category == "AuditEvent" &&
      azurerm_role_assignment.web_app_secrets.role_definition_name == "Key Vault Secrets User"
    )
    error_message = "App and vault diagnostics and managed-identity secret access must be wired."
  }
}

run "public_branding_keeps_safety_defaults" {
  command = plan
  variables {
    display_name = "Client Backup Control"
    support_url  = "https://support.example.invalid/help"
  }
  assert {
    condition = (
      azurerm_linux_web_app.demo.app_settings["APP_DISPLAY_NAME"] == "Client Backup Control" &&
      azurerm_linux_web_app.demo.app_settings["SUPPORT_URL"] == "https://support.example.invalid/help" &&
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_MODE"] == "stub" &&
      azurerm_linux_web_app.demo.app_settings["ENABLE_LIVE_OPERATIONS"] == "false"
    )
    error_message = "Public branding must be wired without changing operational safety defaults."
  }
}

run "reject_non_https_support" {
  command = plan
  variables {
    support_url = "javascript:alert(1)"
  }
  expect_failures = [var.support_url]
}

run "separate_hosting_region" {
  command = plan
  variables {
    app_service_location = "centralus"
  }
  assert {
    condition = (
      azurerm_service_plan.demo.location == "centralus" &&
      azurerm_linux_web_app.demo.location == "centralus" &&
      azurerm_key_vault.demo.location == "eastus2" &&
      azurerm_log_analytics_workspace.demo.location == "eastus2" &&
      azurerm_service_plan.demo.sku_name == "B1"
    )
    error_message = "A hosting region override must move only the plan and app, without changing SKU."
  }
}

run "restricted_vault_network" {
  command = plan
  variables {
    key_vault_public_network_access_enabled = false
  }
  assert {
    condition = (
      !azurerm_key_vault.demo.public_network_access_enabled &&
      azurerm_key_vault.demo.rbac_authorization_enabled &&
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_MODE"] == "stub"
    )
    error_message = "Restricted stub deployments must preserve disabled public vault access and RBAC."
  }
}

run "restricted_demo_requires_assignment_and_role" {
  command = plan
  variables {
    allow_signed_in_demo_operations = false
    enable_three_tier               = true
  }
  assert {
    condition = (
      azuread_service_principal.api.app_role_assignment_required &&
      azurerm_linux_web_app.demo.app_settings["ALLOW_SIGNED_IN_DEMO_OPERATIONS"] == "false" &&
      azurerm_linux_function_app.worker[0].app_settings["ALLOW_SIGNED_IN_DEMO_OPERATIONS"] == "false"
    )
    error_message = "Restricted demos must require API assignment and disable the signed-in demo policy on both apps."
  }
}

run "live_requires_assignment_despite_demo_default" {
  command = plan
  variables {
    commvault_mode     = "live"
    commvault_base_url = "https://commvault.example.com/api"
  }
  assert {
    condition = (
      azuread_service_principal.api.app_role_assignment_required &&
      azurerm_linux_web_app.demo.app_settings["ENABLE_LIVE_OPERATIONS"] == "false" &&
      one(azuread_application.api.app_role).value == "BackupOperator"
    )
    error_message = "The open demo default must not remove live-mode assignment, role, or live-write protections."
  }
}

run "operator_and_spa_assignments" {
  command = plan

  variables {
    operator_object_ids     = ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
    spa_assignment_required = true
  }

  assert {
    condition = (
      length(azuread_app_role_assignment.operator) == 1 &&
      length(azuread_app_role_assignment.spa_access) == 1 &&
      azuread_app_role_assignment.operator["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"].app_role_id == local.operator_role_id &&
      azuread_app_role_assignment.spa_access["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"].app_role_id == "00000000-0000-0000-0000-000000000000"
    )
    error_message = "Optional operator and SPA assignments must remain available."
  }
}

run "live_uses_only_vault_reference" {
  command = plan

  variables {
    commvault_mode         = "live"
    commvault_base_url     = "https://commvault.example.com/commandcenter/api"
    commvault_auth_header  = "Authtoken"
    enable_live_operations = true
  }

  assert {
    condition = (
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_AUTH_VALUE"] == "@Microsoft.KeyVault(SecretUri=https://test-vault.vault.azure.net/secrets/commvault-auth/)" &&
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_AUTH_HEADER"] == "Authtoken" &&
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_BASE_URL"] == "https://commvault.example.com/commandcenter/api" &&
      azurerm_linux_web_app.demo.app_settings["ENABLE_LIVE_OPERATIONS"] == "true"
    )
    error_message = "Live mode must retain the API path and reference, not copy, the credential."
  }
}

run "live_requires_base_url" {
  command = plan
  variables {
    commvault_mode = "live"
  }
  expect_failures = [azurerm_linux_web_app.demo]
}

run "live_operations_require_live_mode" {
  command = plan
  variables {
    enable_live_operations = true
  }
  expect_failures = [azurerm_linux_web_app.demo]
}

run "reject_credentials_in_url" {
  command = plan
  variables {
    commvault_base_url = "https://user:password@commvault.example.com/api"
  }
  expect_failures = [var.commvault_base_url]
}

run "vault_name_handles_hyphenated_app_names" {
  command = plan
  variables {
    app_name = "red--button-demo-with-a-long-app-name"
  }
  assert {
    condition = (
      length(azurerm_key_vault.demo.name) <= 24 &&
      !strcontains(azurerm_key_vault.demo.name, "--") &&
      can(regex("^[a-z][a-z0-9-]+[a-z0-9]$", azurerm_key_vault.demo.name))
    )
    error_message = "Derived vault names must satisfy Azure naming constraints."
  }
}

run "explicit_sync_has_no_three_tier_resources" {
  command = plan
  variables {
    enable_three_tier = false
  }
  assert {
    condition = (
      length(azurerm_storage_account.three_tier) == 0 &&
      length(azurerm_storage_container.work) == 0 &&
      length(azurerm_storage_queue.work) == 0 &&
      length(azurerm_linux_function_app.worker) == 0 &&
      length(azurerm_application_gateway.ingress) == 0 &&
      length(azurerm_virtual_network.gateway) == 0 &&
      length(azurerm_public_ip.gateway) == 0 &&
      azurerm_linux_web_app.demo.app_settings["EXECUTION_MODE"] == "sync" &&
      !contains(keys(azurerm_linux_web_app.demo.app_settings), "STORAGE_ACCOUNT_NAME") &&
      azurerm_linux_web_app.demo.site_config[0].ip_restriction_default_action == "Allow" &&
      !azurerm_linux_web_app.demo.site_config[0].scm_use_main_ip_restriction
    )
    error_message = "Explicit sync must not provision worker/storage/gateway or add ingress restrictions."
  }
}

run "queued_defaults_storage_runtime_and_rbac" {
  command = plan
  assert {
    condition = (
      toset(keys(azurerm_storage_account.three_tier)) == toset(["work", "host"]) &&
      toset(keys(azurerm_storage_container.work)) == toset(["requests", "inventory", "coordination", "stub-state"]) &&
      toset(keys(azurerm_storage_queue.work)) == toset(["requests", "requests-poison"]) &&
      alltrue([for container in azurerm_storage_container.work : container.container_access_type == "private"]) &&
      alltrue([for account in azurerm_storage_account.three_tier :
        !account.shared_access_key_enabled && !account.allow_nested_items_to_be_public &&
        account.https_traffic_only_enabled && account.default_to_oauth_authentication &&
        account.min_tls_version == "TLS1_2" && account.public_network_access == "Enabled"
      ]) &&
      azurerm_storage_account.three_tier["host"].name != azurerm_storage_account.three_tier["work"].name &&
      azurerm_linux_web_app.demo.app_settings["EXECUTION_MODE"] == "queued" &&
      azurerm_linux_web_app.demo.app_settings["STORAGE_ACCOUNT_NAME"] == azurerm_storage_account.three_tier["work"].name
    )
    error_message = "Queued mode requires isolated identity-only host/work storage, private containers and two queues."
  }
  assert {
    condition = (
      length(azurerm_private_endpoint.storage) == 0 &&
      length(azurerm_private_dns_zone.storage) == 0 &&
      length(azurerm_private_dns_zone_virtual_network_link.storage) == 0 &&
      length(azurerm_virtual_network.storage) == 0 &&
      azurerm_linux_web_app.demo.virtual_network_subnet_id == null &&
      azurerm_linux_function_app.worker[0].virtual_network_subnet_id == null
    )
    error_message = "Default queued storage must use authenticated public endpoints without provisioning private networking."
  }
  assert {
    condition = (
      azurerm_linux_function_app.worker[0].service_plan_id == azurerm_service_plan.demo.id &&
      azurerm_linux_function_app.worker[0].enabled &&
      azurerm_service_plan.demo.sku_name == "B1" &&
      azurerm_linux_function_app.worker[0].functions_extension_version == "~4" &&
      azurerm_linux_function_app.worker[0].site_config[0].always_on &&
      azurerm_linux_function_app.worker[0].site_config[0].application_stack[0].python_version == "3.12" &&
      azurerm_linux_function_app.worker[0].storage_uses_managed_identity &&
      azurerm_linux_function_app.worker[0].storage_account_access_key == null &&
      !contains(keys(azurerm_linux_function_app.worker[0].app_settings), "ENTRA_MULTI_TENANT") &&
      !contains(keys(azurerm_linux_function_app.worker[0].app_settings), "ENTRA_ALLOWED_TENANT_IDS") &&
      azurerm_linux_function_app.worker[0].https_only &&
      !azurerm_linux_function_app.worker[0].ftp_publish_basic_authentication_enabled &&
      !azurerm_linux_function_app.worker[0].webdeploy_publish_basic_authentication_enabled &&
      azurerm_linux_function_app.worker[0].app_settings["APP_ENV"] == "production" &&
      azurerm_linux_function_app.worker[0].app_settings["PUBLIC_ORIGIN"] == output.app_url &&
      azurerm_linux_function_app.worker[0].app_settings["ENTRA_API_CLIENT_ID"] == azuread_application.api.client_id &&
      azurerm_linux_function_app.worker[0].app_settings["ENTRA_SPA_CLIENT_ID"] == azuread_application.spa.client_id &&
      azurerm_linux_function_app.worker[0].app_settings["ENTRA_TENANT_ID"] == data.azurerm_client_config.current.tenant_id &&
      azurerm_linux_function_app.worker[0].app_settings["EXECUTION_MODE"] == "queued" &&
      azurerm_linux_function_app.worker[0].app_settings["STORAGE_ACCOUNT_NAME"] == azurerm_storage_account.three_tier["work"].name &&
      azurerm_linux_function_app.worker[0].app_settings["WORK_STORAGE__queueServiceUri"] == azurerm_storage_account.three_tier["work"].primary_queue_endpoint &&
      azurerm_linux_function_app.worker[0].storage_account_name == azurerm_storage_account.three_tier["host"].name &&
      azurerm_linux_function_app.worker[0].app_settings["AzureWebJobsStorage__credential"] == "managedidentity" &&
      azurerm_linux_function_app.worker[0].app_settings["INVENTORY_REFRESH_SCHEDULE"] == "0 */5 * * * *" &&
      azurerm_linux_function_app.worker[0].app_settings["INVENTORY_MAX_AGE_SECONDS"] == "900" &&
      azurerm_linux_function_app.worker[0].app_settings["COMMVAULT_MODE"] == "stub" &&
      azurerm_linux_function_app.worker[0].app_settings["ENABLE_LIVE_OPERATIONS"] == "false" &&
      !contains(keys(azurerm_linux_function_app.worker[0].app_settings), "COMMVAULT_AUTH_VALUE") &&
      !contains(keys(azurerm_linux_function_app.worker[0].app_settings), "AzureWebJobsStorage") &&
      length(azurerm_role_assignment.worker_secrets) == 0
    )
    error_message = "Functions must use Python 3.12/~4 on existing B1, host identity, production Settings validation and safe stub defaults."
  }
  assert {
    condition = (
      length(azurerm_role_assignment.web_blobs) == 2 &&
      azurerm_role_assignment.web_blobs["requests"].role_definition_name == "Storage Blob Data Contributor" &&
      azurerm_role_assignment.web_blobs["inventory"].role_definition_name == "Storage Blob Data Reader" &&
      alltrue([for name, role in azurerm_role_assignment.web_blobs :
        role.scope == azurerm_storage_container.work[name].id &&
        role.principal_id == azurerm_linux_web_app.demo.identity[0].principal_id
      ]) &&
      azurerm_role_assignment.web_queue[0].role_definition_name == "Storage Queue Data Message Sender" &&
      azurerm_role_assignment.web_queue[0].scope == azurerm_storage_queue.work["requests"].id &&
      length(azurerm_role_assignment.worker_blobs) == 4 &&
      alltrue([for name, role in azurerm_role_assignment.worker_blobs :
        role.scope == azurerm_storage_container.work[name].id &&
        role.role_definition_name == "Storage Blob Data Contributor" &&
        role.principal_id == azurerm_linux_function_app.worker[0].identity[0].principal_id
      ]) &&
      length(azurerm_role_assignment.worker_queues) == 2 &&
      alltrue([for name, role in azurerm_role_assignment.worker_queues :
        role.scope == azurerm_storage_queue.work[name].id &&
        role.role_definition_name == "Storage Queue Data Contributor"
      ]) &&
      toset(keys(azurerm_role_assignment.worker_host)) == toset(["Storage Blob Data Owner", "Storage Queue Data Contributor"]) &&
      alltrue([for role in azurerm_role_assignment.worker_host : role.scope == azurerm_storage_account.three_tier["host"].id]) &&
      length(azurerm_application_gateway.ingress) == 0
    )
    error_message = "API and worker must receive narrowly scoped work permissions and isolated host roles without enabling gateway."
  }
}

run "queued_live_existing_apim_credentials" {
  command = plan
  variables {
    enable_three_tier      = true
    commvault_mode         = "live"
    existing_apim_base_url = "https://existing-apim.example.com/approved-api"
  }
  assert {
    condition = (
      azurerm_linux_function_app.worker[0].app_settings["COMMVAULT_MODE"] == "live" &&
      azurerm_linux_function_app.worker[0].app_settings["ENABLE_LIVE_OPERATIONS"] == "false" &&
      azurerm_linux_function_app.worker[0].app_settings["COMMVAULT_BASE_URL"] == var.existing_apim_base_url &&
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_BASE_URL"] == var.existing_apim_base_url &&
      azurerm_linux_function_app.worker[0].app_settings["COMMVAULT_AUTH_VALUE"] == "@Microsoft.KeyVault(SecretUri=https://test-vault.vault.azure.net/secrets/commvault-auth/)" &&
      azurerm_role_assignment.worker_secrets[0].role_definition_name == "Key Vault Secrets User"
    )
    error_message = "Existing APIM must be an explicit live integration using only Key Vault references, not a newly provisioned APIM instance."
  }
}

run "reject_apim_without_three_tier_live_mode" {
  command = plan
  variables {
    existing_apim_base_url = "https://existing-apim.example.com/api"
  }
  expect_failures = [var.existing_apim_base_url]
}

run "reject_insecure_apim" {
  command = plan
  variables {
    enable_three_tier      = true
    commvault_mode         = "live"
    existing_apim_base_url = "http://existing-apim.example.com/api"
  }
  expect_failures = [var.existing_apim_base_url]
}

run "reject_gateway_missing_inputs" {
  command = plan
  variables {
    enable_gateway_ingress = true
  }
  expect_failures = [var.enable_gateway_ingress]
}

run "reject_gateway_public_network" {
  command = plan
  variables {
    gateway_vnet_cidr = "8.8.0.0/16"
  }
  expect_failures = [var.gateway_vnet_cidr]
}

run "reject_gateway_subnet_outside_vnet" {
  command = plan
  variables {
    gateway_subnet_cidr = "10.73.0.0/24"
  }
  expect_failures = [var.gateway_subnet_cidr]
}

run "reject_gateway_non_dns_hostname" {
  command = plan
  variables {
    gateway_hostname = "https://backup.example.com"
  }
  expect_failures = [var.gateway_hostname]
}

run "reject_gateway_certificate_value" {
  command = plan
  variables {
    gateway_certificate_secret_id = "not-a-key-vault-reference"
  }
  expect_failures = [var.gateway_certificate_secret_id]
}

run "gateway_https_only_and_backend_lockdown" {
  command = plan
  variables {
    api_assignment_required       = true
    enable_three_tier             = true
    enable_gateway_ingress        = true
    gateway_hostname              = "backup.example.com"
    gateway_certificate_secret_id = "https://existing-vault.vault.azure.net/secrets/backup-tls"
    gateway_certificate_vault_id  = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/certificates/providers/Microsoft.KeyVault/vaults/existing-vault"
  }
  assert {
    condition = (
      length(azurerm_application_gateway.ingress) == 1 &&
      one(azurerm_application_gateway.ingress[0].frontend_port).port == 443 &&
      length(azurerm_application_gateway.ingress[0].frontend_port) == 1 &&
      one(azurerm_application_gateway.ingress[0].http_listener).protocol == "Https" &&
      one(azurerm_application_gateway.ingress[0].http_listener).require_sni &&
      one(azurerm_application_gateway.ingress[0].backend_http_settings).protocol == "Https" &&
      one(azurerm_application_gateway.ingress[0].backend_http_settings).pick_host_name_from_backend_address &&
      one(azurerm_application_gateway.ingress[0].ssl_certificate).key_vault_secret_id == var.gateway_certificate_secret_id &&
      azurerm_application_gateway.ingress[0].waf_configuration[0].firewall_mode == "Prevention" &&
      azurerm_linux_web_app.demo.site_config[0].ip_restriction_default_action == "Deny" &&
      !azurerm_linux_web_app.demo.site_config[0].scm_use_main_ip_restriction &&
      azurerm_linux_web_app.demo.site_config[0].scm_ip_restriction_default_action == "Deny" &&
      length(azurerm_linux_web_app.demo.site_config[0].scm_ip_restriction) == 0 &&
      one(azurerm_linux_web_app.demo.site_config[0].ip_restriction).virtual_network_subnet_id == azurerm_subnet.gateway[0].id &&
      toset([for endpoint in azurerm_subnet.gateway[0].service_endpoint : endpoint.service]) == toset(["Microsoft.Web", "Microsoft.KeyVault"]) &&
      output.app_url == "https://backup.example.com" &&
      contains(azuread_application.spa.single_page_application[0].redirect_uris, "https://backup.example.com/") &&
      contains(azuread_application.spa.single_page_application[0].redirect_uris, "https://backup.example.com/auth/silent") &&
      !contains(azuread_application.spa.single_page_application[0].redirect_uris, "https://red-button-local-test.azurewebsites.net/") &&
      azuread_service_principal.api.app_role_assignment_required &&
      local.operator_role_id == uuidv5("url", "https://red-button-local-test.azurewebsites.net/BackupOperator")
    )
    error_message = "Gateway must be TLS-only, read existing cert by identity, deny direct web/SCM ingress, and preserve Entra role identity."
  }
}

run "reject_mismatched_certificate_vault" {
  command = plan
  variables {
    enable_three_tier             = true
    enable_gateway_ingress        = true
    gateway_hostname              = "backup.example.com"
    gateway_certificate_secret_id = "https://other-vault.vault.azure.net/secrets/backup-tls"
    gateway_certificate_vault_id  = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/certificates/providers/Microsoft.KeyVault/vaults/existing-vault"
  }
  expect_failures = [azurerm_application_gateway.ingress[0]]
}

run "reject_unrestricted_scm_allowlist" {
  command = plan
  variables {
    gateway_scm_allowed_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.gateway_scm_allowed_cidrs]
}

run "gateway_scm_explicit_deployment_egress" {
  command = plan
  variables {
    enable_three_tier             = true
    enable_gateway_ingress        = true
    gateway_hostname              = "backup.example.com"
    gateway_certificate_secret_id = "https://existing-vault.vault.azure.net/secrets/backup-tls"
    gateway_certificate_vault_id  = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/certificates/providers/Microsoft.KeyVault/vaults/existing-vault"
    gateway_scm_allowed_cidrs     = ["203.0.113.10/32"]
  }
  assert {
    condition = (
      azurerm_linux_web_app.demo.site_config[0].scm_ip_restriction_default_action == "Deny" &&
      one(azurerm_linux_web_app.demo.site_config[0].scm_ip_restriction).ip_address == "203.0.113.10/32" &&
      one(azurerm_linux_web_app.demo.site_config[0].scm_ip_restriction).action == "Allow" &&
      !azurerm_linux_web_app.demo.webdeploy_publish_basic_authentication_enabled &&
      azurerm_linux_web_app.demo.site_config[0].ip_restriction_default_action == "Deny"
    )
    error_message = "Explicit deployment egress must not reopen public web ingress or enable publishing passwords."
  }
}

run "reject_ambiguous_apim_backend" {
  command = plan
  variables {
    enable_three_tier      = true
    commvault_mode         = "live"
    existing_apim_base_url = "https://existing-apim.example.com/api"
    commvault_base_url     = "https://commvault.example.com/api"
  }
  expect_failures = [var.existing_apim_base_url]
}

run "private_storage_routes_both_apps_without_public_access" {
  command = plan
  variables {
    enable_three_tier                 = true
    enable_private_storage_networking = true
  }
  assert {
    condition = (
      length(azurerm_private_endpoint.storage) == 4 &&
      length(azurerm_private_dns_zone.storage) == 2 &&
      length(azurerm_private_dns_zone_virtual_network_link.storage) == 2 &&
      alltrue([for account in azurerm_storage_account.three_tier : account.public_network_access == "Disabled" && !account.shared_access_key_enabled]) &&
      azurerm_linux_web_app.demo.virtual_network_subnet_id == azurerm_subnet.storage_integration[0].id &&
      azurerm_linux_function_app.worker[0].virtual_network_subnet_id == azurerm_subnet.storage_integration[0].id &&
      azurerm_subnet.storage_integration[0].address_prefixes == tolist(["10.73.1.0/24"]) &&
      azurerm_subnet.storage_endpoints[0].address_prefixes == tolist(["10.73.2.0/24"])
    )
    error_message = "Both apps must use privately resolved Blob/Queue endpoints while storage public and key access stay disabled."
  }
}

run "private_storage_off_by_default" {
  command = plan
  assert {
    condition     = length(azurerm_private_endpoint.storage) == 0 && length(azurerm_virtual_network.storage) == 0
    error_message = "Default queued mode must not provision optional private networking."
  }
}

run "reject_private_storage_without_queued_resources" {
  command = plan
  variables {
    enable_three_tier                 = false
    enable_private_storage_networking = true
  }
  expect_failures = [var.enable_private_storage_networking]
}

run "reject_public_storage_vnet" {
  command = plan
  variables {
    storage_vnet_cidr = "8.8.0.0/16"
  }
  expect_failures = [var.storage_vnet_cidr]
}

run "pause_preserves_resources_and_sync_web" {
  command = plan
  variables {
    enable_three_tier         = true
    activate_queued_execution = false
  }
  assert {
    condition = (
      length(azurerm_storage_account.three_tier) == 2 &&
      length(azurerm_linux_function_app.worker) == 1 &&
      !azurerm_linux_function_app.worker[0].enabled &&
      azurerm_linux_web_app.demo.app_settings["EXECUTION_MODE"] == "sync" &&
      azurerm_linux_function_app.worker[0].app_settings["EXECUTION_MODE"] == "queued" &&
      !var.enable_live_operations
    )
    error_message = "Pausing must retain durable resources, stop the worker, and leave the web in safe synchronous mode."
  }
}

run "multi_tenant_org_allowlist_and_runtime" {
  command = plan
  variables {
    enable_multi_tenant = true
    enable_three_tier   = true
    allowed_tenant_ids = [
      "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
      "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    ]
    operator_object_ids     = ["cccccccc-cccc-cccc-cccc-cccccccccccc"]
    api_assignment_required = true
    spa_assignment_required = true
  }
  assert {
    condition = (
      azuread_application.api.sign_in_audience == "AzureADMultipleOrgs" &&
      azuread_application.spa.sign_in_audience == "AzureADMultipleOrgs" &&
      azuread_application_identifier_uri.api.identifier_uri == "api://${azuread_application.api.client_id}" &&
      azuread_application.api.api[0].requested_access_token_version == 2 &&
      one(azuread_application.api.api[0].oauth2_permission_scope).type == "Admin" &&
      one(azuread_application.api.api[0].oauth2_permission_scope).value == "access_as_user" &&
      one(azuread_application.api.app_role).value == "BackupOperator" &&
      azuread_application_pre_authorized.spa.permission_ids == toset([local.scope_id]) &&
      azuread_service_principal.api.app_role_assignment_required &&
      azuread_service_principal.spa.app_role_assignment_required &&
      length(azuread_app_role_assignment.operator) == 1 &&
      length(azuread_app_role_assignment.spa_access) == 1 &&
      azuread_app_role_assignment.operator["cccccccc-cccc-cccc-cccc-cccccccccccc"].resource_object_id == azuread_service_principal.api.object_id &&
      azuread_app_role_assignment.operator["cccccccc-cccc-cccc-cccc-cccccccccccc"].app_role_id == local.operator_role_id
    )
    error_message = "Organizational multi-tenancy must preserve the API identifier, admin-only scope, BackupOperator and home assignment gates."
  }
  assert {
    condition = alltrue([
      for settings in [azurerm_linux_web_app.demo.app_settings, azurerm_linux_function_app.worker[0].app_settings] : (
        settings["ENTRA_MULTI_TENANT"] == "true" &&
        settings["ENTRA_ALLOWED_TENANT_IDS"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa,bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" &&
        settings["ENTRA_TENANT_ID"] == data.azurerm_client_config.current.tenant_id &&
        settings["ENTRA_API_CLIENT_ID"] == azuread_application.api.client_id &&
        settings["ENTRA_SPA_CLIENT_ID"] == azuread_application.spa.client_id &&
        settings["ENABLE_LIVE_OPERATIONS"] == "false"
      )
    ])
    error_message = "Web and worker must receive identical normalized additional-tenant allowlists while retaining home identity and operational safety."
  }
}

run "multi_tenant_sync_and_maximum_allowlist" {
  command = plan
  variables {
    enable_three_tier   = false
    enable_multi_tenant = true
    allowed_tenant_ids  = [for i in range(20) : format("aaaaaaaa-aaaa-aaaa-aaaa-%012d", i)]
  }
  assert {
    condition = (
      length(split(",", azurerm_linux_web_app.demo.app_settings["ENTRA_ALLOWED_TENANT_IDS"])) == 20 &&
      azurerm_linux_web_app.demo.app_settings["ENTRA_MULTI_TENANT"] == "true" &&
      length(azurerm_linux_function_app.worker) == 0 &&
      !azuread_service_principal.api.app_role_assignment_required &&
      !azuread_service_principal.spa.app_role_assignment_required &&
      length(azuread_app_role_assignment.operator) == 0
    )
    error_message = "The 20-tenant boundary must work in synchronous mode without relaxing defaults or creating operators."
  }
}

run "reject_multi_tenant_without_additional_tenants" {
  command = plan
  variables {
    enable_multi_tenant = true
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_allowlist_without_multi_tenant" {
  command = plan
  variables {
    allowed_tenant_ids = ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_tenant_domain" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = ["example.onmicrosoft.com"]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_noncanonical_tenant_guid" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_tenant_guid_whitespace" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = [" aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_null_tenant_guid" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = [null]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_consumers_tenant" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = ["9188040d-6c67-4c5b-b112-36a304b66dad"]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_uppercase_consumers_tenant" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = ["9188040D-6C67-4C5B-B112-36A304B66DAD"]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_home_tenant_as_additional" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = ["11111111-1111-1111-1111-111111111111"]
  }
  expect_failures = [var.allowed_tenant_ids]
}

run "reject_more_than_twenty_additional_tenants" {
  command = plan
  variables {
    enable_multi_tenant = true
    allowed_tenant_ids  = [for i in range(21) : format("aaaaaaaa-aaaa-aaaa-aaaa-%012d", i)]
  }
  expect_failures = [var.allowed_tenant_ids]
}
