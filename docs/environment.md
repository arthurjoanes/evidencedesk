# Ambiente de desenvolvimento observado

Esta página distingue configuração do projeto de recursos efetivamente observados. Leituras antigas de memória/disco livres e versões do host sem um recibo versionado não são usadas como requisito nem como evidência de capacidade.

| Configuração local                                    | Fonte                                                                                |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------ |
| PostgreSQL: teto de 512 MiB; API: 512 MiB             | [Compose principal](../infra/compose/compose.yaml)                                   |
| Worker: teto de 1.536 MiB; frontend: 512 MiB          | [Compose principal](../infra/compose/compose.yaml)                                   |
| Modelos opcionais: 3 GiB e duas CPUs                  | [Perfil ML](../infra/compose/compose.yaml)                                           |
| Serviços publicados em loopback; portas configuráveis | [Compose](../infra/compose/compose.yaml) e [configuração do host](../scripts/ops.py) |
| Observabilidade separada do núcleo                    | [Compose de observabilidade](../infra/compose/observability.yaml)                    |

Esses valores são tetos configurados, não consumo medido nem recomendação universal de hardware. Banco, modelos e arquivos privados usam volumes próprios; sincronizar as fontes não substitui o [backup desses volumes](../scripts/backup.py).

A configuração foi exercitada em **21/09/2026** no [registro de infraestrutura](evidence/infra-config-check.json). Esse registro sustenta checks locais de configuração, não ingestão completa de telemetria nem implantação Azure. A [execução de capacidade](evidence/capacity-summary.json), registrada em **21/09/2026**, identifica suas próprias imagens, condições e limites.

## Evidências posteriores à inspeção inicial

O runtime final chegou à migração 0008; [readiness, UID efetivo 10001, ausência de capabilities, filesystem somente leitura e ausência de OOM](evidence/runtime-final.json) foram observados na imagem indicada nesse registro. [O resultado Azure anterior](evidence/azure-persistence-final.json) manteve os hashes do JSON e do manifesto privados após o restart; não houve nova geração nesse check.

A GPU em container foi posteriormente validada e o laboratório ML executou treino/retrieval próprios; os resultados detalhados estão nos artefatos de `experiments`. O serviço opcional `models` tem perfil `ml`, teto de 3 GiB/2 CPUs, cache somente leitura e nenhum endpoint externo. Não recebe credencial Azure ou URL de banco. Download de pesos e build de dependências são passos separados e explícitos; `HF_HUB_OFFLINE=1` impede download no start desse serviço.

O núcleo operacional e os scripts de backup usam biblioteca padrão; scripts de capacidade/observabilidade usam `httpx` do ambiente do backend. Terraform 1.16.3/AzureRM 5.6.0 foram usados somente para validação local, com cache posterior fora do OneDrive. Um cache inicial `.terraform` permanece ignorado no diretório de IaC; ele não contém state nem segredos de implantação.

[Capacidade](runbooks/capacity.md), [backup/restore](runbooks/backup-restore.md), [observabilidade](runbooks/observability.md) e [limites do perfil Azure hospedado](runbooks/azure-hosted.md) distinguem checks de configuração, execução real e objetivos ainda não comprovados. Os diretórios de dados do Docker não são protegidos automaticamente pela sincronização das fontes.
