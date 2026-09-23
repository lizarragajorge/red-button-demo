locals {
  app_url          = "https://${var.app_name}.azurewebsites.net"
  scope_id         = uuidv5("url", "${local.app_url}/access_as_user")
  operator_role_id = uuidv5("url", "${local.app_url}/BackupOperator")
  tags             = merge({ application = "red-button-demo", managed_by = "terraform" }, var.tags)
}

resource "azuread_application" "api" {
  display_name     = "${var.app_name}-api"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azurerm_client_config.current.object_id]

  api {
    requested_access_token_version = 2

    oauth2_permission_scope {
      id                         = local.scope_id
      value                      = "access_as_user"
      type                       = "Admin"
      enabled                    = true
      admin_consent_display_name = "Access Red Button as the signed-in user"
      admin_consent_description  = "Access the Red Button API on behalf of the signed-in user; operations additionally require BackupOperator."
    }
  }

  app_role {
    id                   = local.operator_role_id
    value                = "BackupOperator"
    display_name         = "Backup Operator"
    description          = "Operate the Red Button backup demo."
    allowed_member_types = ["User"]
    enabled              = true
  }

  lifecycle {
    ignore_changes = [identifier_uris]
  }
}

resource "azuread_application_identifier_uri" "api" {
  application_id = azuread_application.api.id
  identifier_uri = "api://${azuread_application.api.client_id}"
}

resource "azuread_application" "spa" {
  display_name     = "${var.app_name}-spa"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azurerm_client_config.current.object_id]

  single_page_application {
    redirect_uris = ["${local.app_url}/", "http://localhost:5173/", "http://localhost:8080/"]
  }

  required_resource_access {
    resource_app_id = azuread_application.api.client_id

    resource_access {
      id   = local.scope_id
      type = "Scope"
    }
  }
}

resource "azuread_application_pre_authorized" "spa" {
  application_id       = azuread_application.api.id
  authorized_client_id = azuread_application.spa.client_id
  permission_ids       = [local.scope_id]
}

resource "azuread_service_principal" "api" {
  client_id                    = azuread_application.api.client_id
  owners                       = [data.azurerm_client_config.current.object_id]
  app_role_assignment_required = var.api_assignment_required
}

resource "azuread_service_principal" "spa" {
  client_id                    = azuread_application.spa.client_id
  owners                       = [data.azurerm_client_config.current.object_id]
  app_role_assignment_required = var.spa_assignment_required
}

resource "azuread_app_role_assignment" "operator" {
  for_each = var.operator_object_ids

  app_role_id         = local.operator_role_id
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.api.object_id
}

resource "azuread_app_role_assignment" "spa_access" {
  for_each = var.spa_assignment_required ? var.operator_object_ids : toset([])

  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.spa.object_id
}
