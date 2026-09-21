resource "azurerm_virtual_network" "lab" {
  name                = "${var.prefix}-vnet"
  resource_group_name = azurerm_resource_group.lab.name
  location            = var.location
  address_space       = ["10.66.0.0/16"]
}
resource "azurerm_subnet" "apps" {
  name                 = "apps"
  resource_group_name  = azurerm_resource_group.lab.name
  virtual_network_name = azurerm_virtual_network.lab.name
  address_prefixes     = ["10.66.0.0/23"]
  delegation {
    name = "apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.lab.name
  virtual_network_name = azurerm_virtual_network.lab.name
  address_prefixes     = ["10.66.2.0/27"]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "endpoints" {
  name                 = "endpoints"
  resource_group_name  = azurerm_resource_group.lab.name
  virtual_network_name = azurerm_virtual_network.lab.name
  address_prefixes     = ["10.66.3.0/27"]
}
resource "azurerm_private_dns_zone" "data" {
  for_each            = { postgres = "${var.prefix}.postgres.database.azure.com", blob = "privatelink.blob.core.windows.net", vault = "privatelink.vaultcore.azure.net" }
  name                = each.value
  resource_group_name = azurerm_resource_group.lab.name
}
resource "azurerm_private_dns_zone_virtual_network_link" "data" {
  for_each             = azurerm_private_dns_zone.data
  name                 = "${var.prefix}-link"
  private_dns_zone_id  = each.value.id
  virtual_network_id   = azurerm_virtual_network.lab.id
  registration_enabled = false
}
