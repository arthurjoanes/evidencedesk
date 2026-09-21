resource "azurerm_user_assigned_identity" "app" {
  for_each            = toset(["runtime", "frontend"])
  name                = "${var.prefix}-${each.value}"
  resource_group_name = azurerm_resource_group.lab.name
  location            = var.location
}
resource "azurerm_container_registry" "images" {
  name                = "ed${local.suffix}"
  resource_group_name = azurerm_resource_group.lab.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
}
resource "azurerm_role_assignment" "pull" {
  for_each             = azurerm_user_assigned_identity.app
  scope                = azurerm_container_registry.images.id
  role_definition_name = "AcrPull"
  principal_id         = each.value.principal_id
}
resource "azurerm_role_assignment" "objects" {
  scope                = azurerm_storage_container.private["private-objects"].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app["runtime"].principal_id
}
resource "azurerm_role_assignment" "secrets" {
  scope                = azurerm_key_vault.runtime.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app["runtime"].principal_id
}
resource "azurerm_log_analytics_workspace" "logs" {
  name                = "${var.prefix}-logs"
  resource_group_name = azurerm_resource_group.lab.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
}
resource "azurerm_application_insights" "app" {
  name                         = "${var.prefix}-insights"
  resource_group_name          = azurerm_resource_group.lab.name
  location                     = var.location
  workspace_id                 = azurerm_log_analytics_workspace.logs.id
  application_type             = "web"
  local_authentication_enabled = false
}
resource "azurerm_container_app_environment" "app" {
  name                       = "${var.prefix}-apps"
  resource_group_name        = azurerm_resource_group.lab.name
  location                   = var.location
  infrastructure_subnet_id   = azurerm_subnet.apps.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}
output "environment_id" { value = azurerm_container_app_environment.app.id }
output "registry" { value = azurerm_container_registry.images.login_server }
output "runtime_identity_id" { value = azurerm_user_assigned_identity.app["runtime"].id }
output "frontend_identity_id" { value = azurerm_user_assigned_identity.app["frontend"].id }
output "application_insights_id" { value = azurerm_application_insights.app.id }
