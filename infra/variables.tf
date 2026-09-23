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

variable "operator_object_ids" {
  description = "Tenant USER object UUIDs granted BackupOperator on the API. Empty means no operators."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for id in var.operator_object_ids : can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", id))])
    error_message = "Every operator_object_ids entry must be a user object UUID."
  }
}

variable "api_assignment_required" {
  description = "Restrict API token issuance to assigned users. Disabling does not bypass backend role checks."
  type        = bool
  default     = true
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
