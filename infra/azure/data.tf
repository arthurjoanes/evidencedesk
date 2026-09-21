resource "azurerm_postgresql_flexible_server" "database" {
  name                          = "${var.prefix}-pg-${local.suffix}"
  resource_group_name           = azurerm_resource_group.lab.name
  location                      = var.location
  version                       = "17"
  administrator_login           = "ed_bootstrap"
  administrator_password        = var.postgres_administrator_password
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.data["postgres"].id
  public_network_access_enabled = false
  depends_on                    = [azurerm_private_dns_zone_virtual_network_link.data]
}
resource "azurerm_postgresql_flexible_server_configuration" "vector_allowlist" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.database.id
  value     = "VECTOR"
}
resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = "evidencedesk"
  server_id = azurerm_postgresql_flexible_server.database.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
resource "azurerm_storage_account" "objects" {
  name                            = "ed${local.suffix}"
  resource_group_name             = azurerm_resource_group.lab.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  public_network_access           = "Disabled"
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 7 }
    container_delete_retention_policy { days = 7 }
  }
  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
  }
}
resource "azurerm_storage_container" "private" {
  for_each              = toset(["private-objects", "deletion-ledger"])
  name                  = each.value
  storage_account_id    = azurerm_storage_account.objects.id
  container_access_type = "private"
}
resource "azurerm_key_vault" "runtime" {
  name                          = "ed-${local.suffix}"
  resource_group_name           = azurerm_resource_group.lab.name
  location                      = var.location
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  soft_delete_retention_days    = 7
  purge_protection_enabled      = true
  public_network_access_enabled = false
  network_acls {
    default_action = "Deny"
    bypass         = "None"
  }
}
resource "azurerm_private_endpoint" "data" {
  for_each            = { blob = azurerm_storage_account.objects.id, vault = azurerm_key_vault.runtime.id }
  name                = "${var.prefix}-${each.key}-pe"
  resource_group_name = azurerm_resource_group.lab.name
  location            = var.location
  subnet_id           = azurerm_subnet.endpoints.id
  private_service_connection {
    name                           = each.key
    private_connection_resource_id = each.value
    subresource_names              = [each.key]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.data[each.key].id]
  }
}
output "postgres_host" { value = azurerm_postgresql_flexible_server.database.fqdn }
output "storage_account" { value = azurerm_storage_account.objects.name }
output "vault_uri" { value = azurerm_key_vault.runtime.vault_uri }
