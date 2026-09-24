resource "azurerm_virtual_network" "gateway" {
  count               = var.enable_gateway_ingress ? 1 : 0
  name                = "${var.app_name}-ingress"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_service_plan.demo.location
  address_space       = [var.gateway_vnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "gateway" {
  count                = var.enable_gateway_ingress ? 1 : 0
  name                 = "application-gateway"
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.gateway[0].name
  address_prefixes     = [var.gateway_subnet_cidr]
  service_endpoint {
    service = "Microsoft.Web"
  }
  service_endpoint {
    service = "Microsoft.KeyVault"
  }
}

resource "azurerm_network_security_group" "gateway" {
  count               = var.enable_gateway_ingress ? 1 : 0
  name                = "${var.app_name}-ingress"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_service_plan.demo.location
  tags                = local.tags

  security_rule {
    name                       = "HTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "Internet"
    destination_address_prefix = var.gateway_subnet_cidr
  }
  security_rule {
    name                       = "GatewayManager"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "65200-65535"
    source_address_prefix      = "GatewayManager"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "AzureLoadBalancer"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "DenyOtherInbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "gateway" {
  count                     = var.enable_gateway_ingress ? 1 : 0
  subnet_id                 = azurerm_subnet.gateway[0].id
  network_security_group_id = azurerm_network_security_group.gateway[0].id
}

resource "azurerm_public_ip" "gateway" {
  count               = var.enable_gateway_ingress ? 1 : 0
  name                = "${var.app_name}-ingress"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_service_plan.demo.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "gateway" {
  count               = var.enable_gateway_ingress ? 1 : 0
  name                = "${var.app_name}-ingress"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_service_plan.demo.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "gateway_certificate" {
  count                = var.enable_gateway_ingress ? 1 : 0
  scope                = var.gateway_certificate_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.gateway[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_application_gateway" "ingress" {
  count               = var.enable_gateway_ingress ? 1 : 0
  name                = "${var.app_name}-ingress"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_service_plan.demo.location
  tags                = local.tags

  sku {
    name     = "WAF_v2"
    tier     = "WAF_v2"
    capacity = 1
  }
  waf_configuration {
    enabled          = true
    firewall_mode    = "Prevention"
    rule_set_type    = "OWASP"
    rule_set_version = "3.2"
  }
  ssl_policy {
    policy_type = "Predefined"
    policy_name = "AppGwSslPolicy20220101S"
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.gateway[0].id]
  }
  gateway_ip_configuration {
    name      = "gateway"
    subnet_id = azurerm_subnet.gateway[0].id
  }
  frontend_ip_configuration {
    name                 = "public"
    public_ip_address_id = azurerm_public_ip.gateway[0].id
  }
  frontend_port {
    name = "https"
    port = 443
  }
  ssl_certificate {
    name                = "existing-certificate"
    key_vault_secret_id = var.gateway_certificate_secret_id
  }
  http_listener {
    name                           = "https"
    frontend_ip_configuration_name = "public"
    frontend_port_name             = "https"
    protocol                       = "Https"
    host_name                      = var.gateway_hostname
    require_sni                    = true
    ssl_certificate_name           = "existing-certificate"
  }
  backend_address_pool {
    name  = "web"
    fqdns = ["${var.app_name}.azurewebsites.net"]
  }
  backend_http_settings {
    name                                = "web-https"
    cookie_based_affinity               = "Disabled"
    port                                = 443
    protocol                            = "Https"
    request_timeout                     = 60
    pick_host_name_from_backend_address = true
    probe_name                          = "health"
  }
  probe {
    name                                      = "health"
    protocol                                  = "Https"
    path                                      = "/api/health"
    pick_host_name_from_backend_http_settings = true
    interval                                  = 30
    timeout                                   = 10
    unhealthy_threshold                       = 3
    match {
      status_code = ["200"]
    }
  }
  request_routing_rule {
    name                       = "web"
    priority                   = 100
    rule_type                  = "Basic"
    http_listener_name         = "https"
    backend_address_pool_name  = "web"
    backend_http_settings_name = "web-https"
  }

  depends_on = [
    azurerm_role_assignment.gateway_certificate,
    azurerm_subnet_network_security_group_association.gateway
  ]
  lifecycle {
    precondition {
      condition = try(
        lower(split("/", var.gateway_certificate_vault_id)[8]) == lower(split(".", split("/", var.gateway_certificate_secret_id)[2])[0]),
        false
      )
      error_message = "Certificate secret URI and certificate vault ARM ID must identify the same vault."
    }
  }
}
