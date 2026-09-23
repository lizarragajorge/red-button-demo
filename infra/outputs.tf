output "web_app_name" {
  description = "App Service deployment target."
  value       = azurerm_linux_web_app.demo.name
}

output "resource_group_name" {
  description = "Resource group containing all Azure infrastructure."
  value       = azurerm_resource_group.demo.name
}

output "app_url" {
  description = "PUBLIC_ORIGIN and deployed SPA origin."
  value       = local.app_url
}

output "tenant_id" {
  description = "ENTRA_TENANT_ID, derived from the active AzureRM identity."
  value       = data.azurerm_client_config.current.tenant_id
}

output "api_client_id" {
  description = "ENTRA_API_CLIENT_ID; the GUID audience of API v2 access tokens."
  value       = azuread_application.api.client_id
}

output "spa_client_id" {
  description = "ENTRA_SPA_CLIENT_ID; the public MSAL client ID."
  value       = azuread_application.spa.client_id
}

output "api_scope" {
  description = "Delegated scope requested by MSAL."
  value       = "${azuread_application_identifier_uri.api.identifier_uri}/access_as_user"
}

output "api_service_principal_object_id" {
  description = "API enterprise application object ID for assignment administration."
  value       = azuread_service_principal.api.object_id
}

output "backup_operator_role_id" {
  description = "BackupOperator app role ID."
  value       = local.operator_role_id
}

output "key_vault_name" {
  description = "Vault to populate externally; no secret values are managed by Terraform."
  value       = azurerm_key_vault.demo.name
}

output "key_vault_id" {
  description = "Vault resource ID for external RBAC administration."
  value       = azurerm_key_vault.demo.id
}

output "web_app_principal_id" {
  description = "Managed identity used to resolve Key Vault references."
  value       = azurerm_linux_web_app.demo.identity[0].principal_id
}

output "log_analytics_workspace_id" {
  description = "Workspace receiving web app and vault diagnostics."
  value       = azurerm_log_analytics_workspace.demo.id
}

output "application_insights_id" {
  description = "Workspace-based Application Insights resource."
  value       = azurerm_application_insights.demo.id
}
