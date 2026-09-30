variable "subscription_id" {
  description = "Azure subscription UUID. Supply locally or via TF_VAR_subscription_id."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a UUID."
  }
}

variable "app_name" {
  description = "Globally unique App Service name; also prefixes the demo's resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,38}[a-z0-9]$", var.app_name))
    error_message = "app_name must be 3-40 lowercase letters, digits or hyphens, start with a letter, and end with a letter or digit."
  }
}

variable "location" {
  description = "Azure region for the resource group, monitoring, vault, and hosting unless overridden."
  type        = string
  default     = "eastus2"
}

variable "app_service_location" {
  description = "Optional App Service/plan region override when the primary region lacks hosting quota."
  type        = string
  default     = null

  validation {
    condition     = var.app_service_location == null || can(regex("^[a-z][a-z0-9]+$", var.app_service_location))
    error_message = "app_service_location must be null or an Azure region code, for example centralus."
  }
}

variable "display_name" {
  description = "Public operator-facing app name. Does not change resource names or safety controls."
  type        = string
  default     = "Red Button"

  validation {
    condition     = length(trimspace(var.display_name)) > 0 && length(var.display_name) <= 60 && !can(regex("[[:cntrl:]]", var.display_name))
    error_message = "display_name must be 1-60 printable characters, not blank."
  }
}

variable "support_url" {
  description = "Optional public HTTPS support destination. Never include credentials or secrets."
  type        = string
  default     = ""

  validation {
    condition     = var.support_url == "" || (length(var.support_url) <= 2048 && can(regex("^https://[^/@?#[:space:]\\\\]+([/?#][^[:space:]\\\\]*)?$", var.support_url)))
    error_message = "support_url must be empty or an HTTPS URL without credentials, whitespace, or backslashes."
  }
}

variable "service_plan_sku" {
  description = "Dedicated Linux App Service SKU supporting Always On (Basic or higher)."
  type        = string
  default     = "B1"

  validation {
    condition     = can(regex("^(B[1-3]|S[1-3]|P[0-9]+v[234]|P[1-3]mv[34])$", var.service_plan_sku))
    error_message = "Choose a Basic, Standard, or Premium dedicated SKU, for example B1, S1, or P1v3."
  }
}

variable "enable_multi_tenant" {
  description = "Opt in to organizational multi-tenant sign-in with an explicit additional-tenant allowlist. The home tenant is always allowed."
  type        = bool
  default     = false
  nullable    = false
}

variable "allowed_tenant_ids" {
  description = "Up to 20 additional organizational tenant GUIDs. Requires enable_multi_tenant; omit the implicitly allowed home tenant."
  type        = set(string)
  default     = []
  nullable    = false

  validation {
    condition     = alltrue([for id in var.allowed_tenant_ids : can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", id))])
    error_message = "Every allowed_tenant_ids entry must be a canonical hyphenated tenant GUID."
  }

  validation {
    condition     = alltrue([for id in var.allowed_tenant_ids : try(lower(id) != "9188040d-6c67-4c5b-b112-36a304b66dad", false)])
    error_message = "allowed_tenant_ids must not include the Microsoft personal-account consumers tenant."
  }

  validation {
    condition     = length(var.allowed_tenant_ids) <= 20
    error_message = "allowed_tenant_ids may contain at most 20 additional tenants."
  }

  validation {
    condition     = var.enable_multi_tenant ? length(var.allowed_tenant_ids) > 0 : length(var.allowed_tenant_ids) == 0
    error_message = "enable_multi_tenant requires at least one additional tenant; allowed_tenant_ids must be empty when multi-tenant sign-in is disabled."
  }

  validation {
    condition     = alltrue([for id in var.allowed_tenant_ids : try(lower(id) != lower(data.azurerm_client_config.current.tenant_id), false)])
    error_message = "Omit the home tenant from allowed_tenant_ids; it is always allowed implicitly."
  }
}

variable "operator_object_ids" {
  description = "Home-tenant USER object UUIDs granted BackupOperator on the local API enterprise app. External tenant admins manage their own assignments. Empty means no local BackupOperator assignments."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for id in var.operator_object_ids : can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", id))])
    error_message = "Every operator_object_ids entry must be a user object UUID."
  }
}

variable "api_assignment_required" {
  description = "Override API assignment requirements. Null allows signed-in demo users in open stub mode and requires assignment otherwise. Live mutations always require BackupOperator."
  type        = bool
  default     = null
}

variable "spa_assignment_required" {
  description = "Also restrict SPA sign-in to operator_object_ids, assigning their default access role."
  type        = bool
  default     = false
}

variable "commvault_mode" {
  description = "stub uses a private in-process HTTPX ASGITransport with no stub socket; live requires an externally populated vault secret."
  type        = string
  default     = "stub"

  validation {
    condition     = contains(["stub", "live"], var.commvault_mode)
    error_message = "commvault_mode must be stub or live."
  }
}

variable "allow_signed_in_demo_operations" {
  description = "Allow any authenticated approved-tenant user to operate the simulator. Has no effect on live operations, which require BackupOperator and the live gate."
  type        = bool
  default     = true
  nullable    = false
}

variable "commvault_base_url" {
  description = "Live Commvault HTTPS base URL including API path prefix, without credentials, query, or fragment."
  type        = string
  default     = ""

  validation {
    condition     = var.commvault_base_url == "" || can(regex("^https://[^/@?#[:space:]]+(/[^?#[:space:]]*)?$", var.commvault_base_url))
    error_message = "commvault_base_url must be empty or an HTTPS URL without credentials, query, or fragment."
  }
}

variable "commvault_auth_header" {
  description = "Header carrying the vault secret's exact value."
  type        = string
  default     = "Authorization"

  validation {
    condition     = contains(["Authorization", "Authtoken"], var.commvault_auth_header)
    error_message = "commvault_auth_header must be Authorization or Authtoken."
  }
}

variable "commvault_secret_name" {
  description = "Name only of the externally managed vault secret; never provide its value to Terraform."
  type        = string
  default     = "commvault-auth"

  validation {
    condition     = can(regex("^[a-zA-Z0-9-]{1,127}$", var.commvault_secret_name))
    error_message = "commvault_secret_name must be 1-127 letters, digits or hyphens."
  }
}

variable "key_vault_public_network_access_enabled" {
  description = "Allow public Key Vault networking. Disable for restricted stub deployments; live mode needs an approved reachable vault network path."
  type        = bool
  default     = true
}

variable "enable_live_operations" {
  description = "Explicit additional opt-in for live operations; leave false until reviewed."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Additional Azure resource tags."
  type        = map(string)
  default     = {}
}

variable "enable_three_tier" {
  description = "Provision durable queued execution, private storage containers and a Functions worker on the existing plan by default. False explicitly selects synchronous hosting without durable resources."
  type        = bool
  default     = true
}

variable "existing_apim_base_url" {
  description = "Optional existing, operator-configured APIM HTTPS API base URL. No APIM instance, API, policy, backend or stub host is provisioned."
  type        = string
  default     = ""
  validation {
    condition = var.existing_apim_base_url == "" || (
      can(regex("^https://[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?(/[^?#[:space:]\\\\]*)?$", var.existing_apim_base_url)) &&
      var.enable_three_tier && var.commvault_mode == "live" && var.commvault_base_url == ""
    )
    error_message = "existing_apim_base_url requires three-tier live mode, an empty commvault_base_url, and an HTTPS DNS URL without credentials, port, query or fragment. Routes/policies must already exist."
  }
}

variable "enable_gateway_ingress" {
  description = "Opt in to a separately billed HTTPS-only WAF_v2 gateway and lock down web/SCM ingress. Requires three-tier mode, DNS and an existing Key Vault certificate."
  type        = bool
  default     = false
  validation {
    condition = !var.enable_gateway_ingress || (
      var.enable_three_tier && var.gateway_hostname != "" &&
      var.gateway_certificate_secret_id != "" && var.gateway_certificate_vault_id != ""
    )
    error_message = "Gateway ingress requires enable_three_tier, gateway_hostname, gateway_certificate_secret_id and gateway_certificate_vault_id."
  }
}

variable "gateway_hostname" {
  description = "Existing DNS hostname to point to the gateway IP; certificate must cover it. No DNS zone/record is managed."
  type        = string
  default     = ""
  validation {
    condition     = var.gateway_hostname == "" || (length(var.gateway_hostname) <= 253 && can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.gateway_hostname)))
    error_message = "gateway_hostname must be empty or a lowercase fully qualified DNS hostname, not a URL or wildcard."
  }
}

variable "gateway_certificate_secret_id" {
  description = "Versionless HTTPS Key Vault secret URI containing an enabled, exportable PFX certificate. Never the certificate value."
  type        = string
  default     = ""
  validation {
    condition     = var.gateway_certificate_secret_id == "" || can(regex("^https://[a-zA-Z0-9-]+\\.vault\\.azure\\.net/secrets/[a-zA-Z0-9-]+/?$", var.gateway_certificate_secret_id))
    error_message = "Use a versionless https://<vault>.vault.azure.net/secrets/<certificate> URI."
  }
}

variable "gateway_certificate_vault_id" {
  description = "ARM resource ID of the existing RBAC-enabled certificate vault, reachable by Application Gateway. Used only to assign certificate-reading permission."
  type        = string
  default     = ""
  validation {
    condition     = var.gateway_certificate_vault_id == "" || can(regex("(?i)^/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/]+/providers/Microsoft.KeyVault/vaults/[a-z0-9-]+$", var.gateway_certificate_vault_id))
    error_message = "gateway_certificate_vault_id must be an existing Key Vault ARM resource ID."
  }
}

variable "gateway_vnet_cidr" {
  description = "Dedicated nonoverlapping RFC1918 IPv4 gateway VNet range."
  type        = string
  default     = "10.72.0.0/16"
  validation {
    condition = can(cidrnetmask(var.gateway_vnet_cidr)) && can(regex("^(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.)", var.gateway_vnet_cidr)) && try(
      tonumber(split("/", var.gateway_vnet_cidr)[1]) >= 16 && tonumber(split("/", var.gateway_vnet_cidr)[1]) <= 24 &&
      cidrhost(var.gateway_vnet_cidr, 0) == split("/", var.gateway_vnet_cidr)[0], false
    )
    error_message = "gateway_vnet_cidr must be a canonical private IPv4 network with /16 through /24 prefix."
  }
}

variable "gateway_subnet_cidr" {
  description = "Dedicated /24 gateway subnet within gateway_vnet_cidr; no other workloads may use it."
  type        = string
  default     = "10.72.0.0/24"
  validation {
    condition = can(cidrnetmask(var.gateway_subnet_cidr)) && try(
      split("/", var.gateway_subnet_cidr)[1] == "24" &&
      cidrhost(var.gateway_subnet_cidr, 0) == split("/", var.gateway_subnet_cidr)[0] &&
      cidrhost("${split("/", var.gateway_subnet_cidr)[0]}/${split("/", var.gateway_vnet_cidr)[1]}", 0) == cidrhost(var.gateway_vnet_cidr, 0), false
    )
    error_message = "gateway_subnet_cidr must be a canonical /24 IPv4 subnet contained in gateway_vnet_cidr."
  }
}

variable "gateway_scm_allowed_cidrs" {
  description = "Explicit trusted public IPv4 deployment egress ranges (/24-/32). Gateway mode denies SCM access by default; Entra deployment authorization is still required."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([for cidr in var.gateway_scm_allowed_cidrs : can(cidrnetmask(cidr)) && try(
      tonumber(split("/", cidr)[1]) >= 24 && tonumber(split("/", cidr)[1]) <= 32 &&
      cidrhost(cidr, 0) == split("/", cidr)[0], false
    )])
    error_message = "SCM deployment allowlist must contain canonical IPv4 CIDRs with /24 through /32 prefixes; broad internet access is not allowed."
  }
}
