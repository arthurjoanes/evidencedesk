# Separate root: main foundation does NOT instantiate this runtime contract.
terraform {
  required_version = "= 1.16.3"
  required_providers { azurerm = { source = "hashicorp/azurerm", version = "= 5.6.0" } }
}
provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}
variable "runtime_rollout_ready" {
  type        = bool
  default     = false
  description = "Enable only after durable remote GC/ledger, Blob integration and identity/Monitor gates are implemented and verified."
}
variable "subscription_id" { type = string }
variable "resource_group_name" { type = string }
variable "prefix" { type = string }
variable "environment_id" { type = string }
variable "registry_server" { type = string }
variable "runtime_identity_id" { type = string }
variable "frontend_identity_id" { type = string }
variable "backend_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[a-f0-9]{64}$", var.backend_image))
    error_message = "Use an immutable image digest."
  }
}
variable "frontend_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[a-f0-9]{64}$", var.frontend_image))
    error_message = "Use an immutable image digest."
  }
}
variable "database_secret_uri" { type = string }
variable "azure_key_secret_uri" { type = string }
variable "metrics_secret_uri" { type = string }
variable "cursor_secret_uri" { type = string }
variable "allowed_origin" { type = string }
variable "telemetry_endpoint" { type = string }
variable "azure_inference_base_url" { type = string }
variable "azure_deployment" { type = string }
locals {
  secrets            = { database = var.database_secret_uri, azure = var.azure_key_secret_uri, metrics = var.metrics_secret_uri, cursor = var.cursor_secret_uri }
  environment        = { ED_COOKIE_SECURE = "true", ED_ALLOWED_ORIGINS = var.allowed_origin, ED_AI_PROVIDER = "azure_openai", AZURE_OPENAI_BASE_URL = var.azure_inference_base_url, AZURE_OPENAI_DEPLOYMENT = var.azure_deployment, OTEL_EXPORTER_OTLP_ENDPOINT = var.telemetry_endpoint }
  secret_environment = { ED_DATABASE_URL = "database", AZURE_OPENAI_API_KEY = "azure", ED_METRICS_TOKEN = "metrics", ED_CURSOR_SECRET = "cursor" }
}
resource "azurerm_container_app" "backend" {
  lifecycle {
    precondition {
      condition     = var.runtime_rollout_ready
      error_message = "Runtime rollout is blocked: implement and verify durable remote cleanup/ledger, Blob integration, identity and Monitor authentication first."
    }
  }

  for_each                     = toset(["api", "worker"])
  name                         = "${var.prefix}-${each.value}"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.environment_id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  identity {
    type         = "UserAssigned"
    identity_ids = [var.runtime_identity_id]
  }
  registry {
    server   = var.registry_server
    identity = var.runtime_identity_id
  }
  dynamic "secret" {
    for_each = local.secrets
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = var.runtime_identity_id
    }
  }
  dynamic "ingress" {
    for_each = each.value == "api" ? [1] : []
    content {
      external_enabled           = false
      target_port                = 8106
      transport                  = "http"
      allow_insecure_connections = false
      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }
  template {
    min_replicas = 1 # Worker polling has no external wake trigger.
    max_replicas = 2 # Worker needs explicit operational scaling; no queue autoscaler yet.
    dynamic "http_scale_rule" {
      for_each = each.value == "api" ? [1] : []
      content {
        name                = "http"
        concurrent_requests = "20"
      }
    }
    container {
      name    = each.value
      image   = var.backend_image
      cpu     = each.value == "api" ? 0.5 : 1
      memory  = each.value == "api" ? "1Gi" : "2Gi"
      command = each.value == "api" ? ["uvicorn", "evidencedesk.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8106", "--no-access-log", "--limit-concurrency", "64"] : ["python", "-m", "evidencedesk.worker"]
      dynamic "env" {
        for_each = local.environment
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_environment
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      dynamic "readiness_probe" {
        for_each = each.value == "api" ? [1] : []
        content {
          transport = "HTTP"
          port      = 8106
          path      = "/api/v1/health/ready"
        }
      }
      dynamic "liveness_probe" {
        for_each = each.value == "api" ? [1] : []
        content {
          transport = "HTTP"
          port      = 8106
          path      = "/api/v1/health/live"
        }
      }
    }
  }
}
resource "azurerm_container_app" "frontend" {
  lifecycle {
    precondition {
      condition     = var.runtime_rollout_ready
      error_message = "Runtime rollout is blocked: implement and verify durable remote cleanup/ledger, Blob integration, identity and Monitor authentication first."
    }
  }

  name                         = "${var.prefix}-web"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.environment_id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  identity {
    type         = "UserAssigned"
    identity_ids = [var.frontend_identity_id]
  }
  registry {
    server   = var.registry_server
    identity = var.frontend_identity_id
  }
  ingress {
    external_enabled           = true
    target_port                = 3106
    transport                  = "http"
    allow_insecure_connections = false
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
  template {
    min_replicas = 0
    max_replicas = 2
    http_scale_rule {
      name                = "http"
      concurrent_requests = "20"
    }
    container {
      name   = "web"
      image  = var.frontend_image
      cpu    = 0.5
      memory = "1Gi"
      env {
        name  = "API_INTERNAL_URL"
        value = "https://${azurerm_container_app.backend["api"].ingress[0].fqdn}"
      }
      env {
        name  = "PORT"
        value = "3106"
      }
    }
  }
}
output "state" { value = "contract-only-not-approved-for-rollout" }
