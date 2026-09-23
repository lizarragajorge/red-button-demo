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
  api_assignment_required                 = true
  spa_assignment_required                 = false
  commvault_mode                          = "stub"
  enable_live_operations                  = false
  key_vault_public_network_access_enabled = true
}

run "secure_stub_defaults" {
  command = plan

  assert {
    condition = (
      azurerm_linux_web_app.demo.app_settings["COMMVAULT_MODE"] == "stub" &&
      azurerm_linux_web_app.demo.app_settings["APP_DISPLAY_NAME"] == "Red Button" &&
      azurerm_linux_web_app.demo.app_settings["SUPPORT_URL"] == "" &&
      azurerm_linux_web_app.demo.app_settings["ENABLE_LIVE_OPERATIONS"] == "false" &&
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
      azuread_service_principal.api.app_role_assignment_required &&
      !azuread_service_principal.spa.app_role_assignment_required &&
      length(azuread_app_role_assignment.operator) == 0 &&
      azuread_application.api.api[0].requested_access_token_version == 2 &&
      one(azuread_application.api.app_role).value == "BackupOperator" &&
      one(azuread_application.api.app_role).allowed_member_types == toset(["User"]) &&
      azuread_application.spa.single_page_application[0].redirect_uris == toset(["https://red-button-local-test.azurewebsites.net/", "http://localhost:5173/", "http://localhost:8080/"]) &&
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
