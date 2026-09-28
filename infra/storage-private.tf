variable "enable_private_storage_networking" {
  description = "Storage networking switch: false uses public HTTPS endpoints; true adds private endpoints, DNS and outbound app VNet integration. Both modes require managed identity/RBAC and disable anonymous and shared-key access. Private mode requires enable_three_tier."
  type        = bool
  default     = false
  validation {
    condition     = !var.enable_private_storage_networking || var.enable_three_tier
    error_message = "Private storage networking requires enable_three_tier."
  }
}

variable "storage_vnet_cidr" {
  description = "Canonical private /16 IPv4 network for outbound app integration and storage private endpoints."
  type        = string
  default     = "10.73.0.0/16"
  validation {
    condition = can(cidrnetmask(var.storage_vnet_cidr)) && try(
      split("/", var.storage_vnet_cidr)[1] == "16" &&
      cidrhost(var.storage_vnet_cidr, 0) == split("/", var.storage_vnet_cidr)[0] &&
      (startswith(var.storage_vnet_cidr, "10.") || startswith(var.storage_vnet_cidr, "192.168.") ||
        (split(".", var.storage_vnet_cidr)[0] == "172" && tonumber(split(".", var.storage_vnet_cidr)[1]) >= 16 &&
      tonumber(split(".", var.storage_vnet_cidr)[1]) <= 31)), false
    )
    error_message = "storage_vnet_cidr must be a canonical RFC1918 /16 IPv4 network."
  }
}

locals {
  private_storage_services = var.enable_private_storage_networking ? toset(["blob", "queue"]) : toset([])
  private_storage_endpoints = var.enable_private_storage_networking ? {
    for pair in setproduct(["work", "host"], ["blob", "queue"]) :
    "${pair[0]}-${pair[1]}" => { account = pair[0], service = pair[1] }
  } : {}
}

resource "azurerm_virtual_network" "storage" {
  count               = var.enable_private_storage_networking ? 1 : 0
  name                = "${var.app_name}-storage"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_service_plan.demo.location
  address_space       = [var.storage_vnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "storage_integration" {
  count                = var.enable_private_storage_networking ? 1 : 0
  name                 = "app-integration"
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.storage[0].name
  address_prefixes     = [cidrsubnet(var.storage_vnet_cidr, 8, 1)]
  delegation {
    name = "app-service"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

resource "azurerm_subnet" "storage_endpoints" {
  count                = var.enable_private_storage_networking ? 1 : 0
  name                 = "private-endpoints"
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.storage[0].name
  address_prefixes     = [cidrsubnet(var.storage_vnet_cidr, 8, 2)]
}

resource "azurerm_private_dns_zone" "storage" {
  for_each            = local.private_storage_services
  name                = "privatelink.${each.key}.core.windows.net"
  resource_group_name = azurerm_resource_group.demo.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "storage" {
  for_each             = local.private_storage_services
  name                 = "${var.app_name}-${each.key}"
  private_dns_zone_id  = azurerm_private_dns_zone.storage[each.key].id
  virtual_network_id   = azurerm_virtual_network.storage[0].id
  registration_enabled = false
  tags                 = local.tags
}

resource "azurerm_private_endpoint" "storage" {
  for_each            = local.private_storage_endpoints
  name                = "${var.app_name}-${each.key}"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_service_plan.demo.location
  subnet_id           = azurerm_subnet.storage_endpoints[0].id
  tags                = local.tags
  private_service_connection {
    name                           = each.key
    private_connection_resource_id = azurerm_storage_account.three_tier[each.value.account].id
    subresource_names              = [each.value.service]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "storage"
    private_dns_zone_ids = [azurerm_private_dns_zone.storage[each.value.service].id]
  }
}
