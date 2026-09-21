terraform {
  required_version = "= 1.16.3"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "= 5.6.0" }
  }
}
provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
}
variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "prefix" {
  type    = string
  default = "evidencedesk"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,11}$", var.prefix))
    error_message = "Use 3-12 lowercase characters, starting with a letter."
  }
}
variable "postgres_administrator_password" {
  type      = string
  sensitive = true
  validation {
    condition     = length(var.postgres_administrator_password) >= 20
    error_message = "A bootstrap password needs at least20 characters; inject outside the repository."
  }
}
locals { suffix = substr(sha256("${var.subscription_id}/${var.resource_group_name}/${var.prefix}"), 0, 10) }
resource "azurerm_resource_group" "lab" {
  name     = var.resource_group_name
  location = var.location
  tags     = { project = "EvidenceDesk", purpose = "hosted-preparation" }
}
output "state" { value = "foundation-only-runtime-blocked" }
