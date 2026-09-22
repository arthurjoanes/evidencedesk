# Azure hospedado: preparação, não implantação

O ambiente executado e testado é o Compose local com inferência Azure. Os arquivos Terraform em `infra/azure` são uma preparação de infraestrutura; nenhum recurso Azure foi criado, alterado ou validado por uma chamada de gerenciamento. [A evidência](../evidence/azure-iac-validation.json) registra `terraform fmt -check`, inicialização com backend desativado e `terraform validate` sem erros/avisos, não um deploy bem-sucedido.

A raiz `infra/azure` prepara rede, PostgreSQL Flexible Server 17, Blob privado, Key Vault, ACR, identidade gerenciada e observabilidade. Ele deliberadamente não instancia a raiz separada `infra/azure/runtime-contract`. Essa segunda raiz descreve o contrato futuro de API, worker e frontend; validá-la não torna o armazenamento local compatível com várias máquinas.

## Decisões e limites

- API e worker usam uma identidade de runtime; o frontend possui outra identidade, somente com AcrPull. Acesso Blob fica limitado ao container `private-objects`; o ledger tem outro container, sem permissão concedida ao runtime até seu protocolo remoto ser implementado.
- PostgreSQL usa subnet delegada e DNS privado; Blob e Key Vault usam private endpoints, DNS e rede pública desativada. O ACR Basic conserva endpoint autenticado público para evitar custo Premium prematuro; o usuário administrador está desativado.
- Segredos de runtime seriam referências versionadas ao Key Vault. O segredo de banco precisa ser do papel `ed_app`, nunca `ed_owner` ou do administrador. Bootstrap SQL, instalação efetiva de `vector`, migrações e seed são etapas separadas e ainda não executadas na Azure. O allowlist `azure.extensions=VECTOR` não executa `CREATE EXTENSION`.
- O worker de polling PostgreSQL mantém `minReplicas=1`. O teto de 2 não o faz escalar automaticamente: não há regra KEDA por tamanho da fila nesta preparação. API e frontend têm regras HTTP. O pool e `max_connections` precisarão ser dimensionados considerando réplicas antigas e novas durante atualizações.
- O SKU Burstable, disco de 32 GB, backup de 7 dias e ausência de HA são escolhas de laboratório, não garantia de capacidade ou disponibilidade. Sem valor mensal inventado: antes de provisionar, calcular região, instâncias mínimas, PostgreSQL, private endpoints, ACR, tráfego e retenção no Azure Pricing Calculator. Orçamentos notificam, não desligam recursos automaticamente.
- Log Analytics tem retenção de 30 dias e quota diária de 1 GB. Isso limita coleta e pode causar lacunas; não é um teto absoluto de fatura. Alertas de ausência de telemetria e de cap atingido precisam ser configurados fora do fluxo que pode ficar sem dados. Application Insights exige autenticação Entra; o exporter/MI e RBAC de Monitor ainda não foram ensaiados.

## Bloqueadores antes de qualquer rollout

O contrato de runtime possui `runtime_rollout_ready=false` por padrão e uma precondition nos recursos de aplicação. Preencher os demais parâmetros não basta para aplicar o contrato sem revisar os bloqueadores abaixo.

1. Integrar Blob ao core através de operações duráveis de quarentena/publicação/cleanup, sem chamadas de rede enquanto uma transação PostgreSQL mantém locks. O adaptador isolado e seus testes não substituem essa integração.
2. Implementar ledger remoto independente com serialização, append/checkpoint consistente e replay fechado. Um volume local de Container Apps não é armazenamento compartilhado durável entre máquinas.
3. Definir backup consistente entre ponto do banco e versões imutáveis dos objetos. PITR do PostgreSQL não inclui Blob nem o ledger atual. Restauração continua isolada, aplica o ledger mais recente e verifica hashes/referências antes de reabrir. Soft delete/versionamento do Blob preservam bytes durante sua retenção; expurgo legal precisa considerar essas versões, sem afirmar remoção física imediata.
4. Validar DNS/rotas/identidades, rotação de segredos, observabilidade sem conteúdo sensível, mapeamento de roles RLS e autenticação TLS ao banco. Testar rejeição entre tenants e pós-revogação no destino.
5. Ensaiar readiness, rollback, drenagem e atualização com réplicas sobrepostas, quotas regionais, orçamento, custos e alertas. Somente então publicar imagens por digest e promover o contrato de runtime.

O protocolo local de backup/restore e a inferência Azure já executada permanecem evidências separadas. Esta preparação não altera o projeto Foundry existente nem cria outro deployment de modelo.

## Validação reproduzível

Use Terraform `1.16.3` e AzureRM `5.6.0`, ambos fixados nas configurações; as duas raízes incluem `.terraform.lock.hcl`. O ZIP Windows usado veio da [distribuição oficial HashiCorp](https://releases.hashicorp.com/terraform/1.16.3/) e seu SHA-256 `6f908a90e5637afe72705290afd1cd71fc4f2877303ca77f05a8c6ead196b11c` foi conferido com SHA256SUMS. O provider foi verificado pela assinatura HashiCorp durante `init`. Binário e cache das validações seguintes ficam fora do repositório/OneDrive.

```powershell
.venv/Scripts/python.exe scripts/check_azure_iac.py --terraform C:/caminho/terraform.exe --data-root C:/cache/evidencedesk-terraform
```

O script executa somente format check, `init -backend=false -lockfile=readonly` e `validate -json`. O download do provider usa o Registry público; não há `az login`, consulta de assinatura, `plan`, `apply`, `what-if` ou validação ARM remota. Não foram verificados quotas, políticas, SKU regional ou acesso de rede da assinatura.

Antes de qualquer implantação futura, definir backend remoto cifrado e com acesso restrito: `sensitive=true` evita a exibição casual, mas não remove segredos do state. O executor de Terraform também precisará de acesso à rede privada e RBAC de dados para gerenciar containers de Blob; desativar chaves compartilhadas exige autenticação Entra. A identidade do executor é diferente das identidades da aplicação. Não salvar `tfvars` com segredos nem state no repositório.

Referências oficiais: [escala de Container Apps](https://learn.microsoft.com/azure/container-apps/scale-app), [schema de Container Apps](https://learn.microsoft.com/azure/templates/microsoft.app/containerapps), [PostgreSQL privado](https://learn.microsoft.com/azure/postgresql/network/concepts-networking-private), [pgvector](https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-use-pgvector), [schema Blob](https://learn.microsoft.com/azure/templates/microsoft.storage/2025-06-01/storageaccounts/blobservices/containers), [Application Insights](https://learn.microsoft.com/azure/templates/microsoft.insights/2020-02-02/components).
