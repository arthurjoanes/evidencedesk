# EvidenceDesk

Investigação de pedidos com fontes verificáveis e revisão por outra pessoa.

<!-- Navegação do README -->
<p>
  <a href="#demonstração"><img src="docs/readme/badges/demo.svg" alt="Demonstração" width="139" height="28"></a>
  <a href="#arquitetura"><img src="docs/readme/badges/architecture.svg" alt="Arquitetura" width="126" height="28"></a>
  <a href="#executar-localmente"><img src="docs/readme/badges/run.svg" alt="Executar localmente" width="107" height="28"></a>
  <a href="#verificação-e-evidências"><img src="docs/readme/badges/evidence.svg" alt="Verificação e evidências" width="119" height="28"></a>
  <a href="https://www.linkedin.com/in/arthur-joanes-6a2967373/"><img src="docs/readme/badges/linkedin.svg" alt="Arthur Joanes no LinkedIn" width="108" height="28"></a>
</p>

## Visão geral

Desenvolvi o EvidenceDesk para investigar casos em que o pagamento foi confirmado, mas o pedido continua pendente. A aplicação reúne eventos, snapshots e documentos; separa regras determinísticas de rascunhos opcionais de IA e exige outra conta para aprovar uma revisão. É uma demonstração sintética, sem adoção comercial ou ganho de produtividade medido. Fontes conferidas em **22/09/2026**: [conciliação](backend/src/evidencedesk/reconciliation/rules.py), [revisões](backend/src/evidencedesk/reviews/service.py) e [seed](backend/src/evidencedesk/seed.py).

<a id="na-prática"></a>
<a id="uma-investigação-do-início-ao-fim"></a>

## Demonstração

![Página principal do EvidenceDesk](docs/readme/home.png)

_Imagem versionada da página principal, conferida nesta revisão documental em 22/09/2026. A imagem apresenta a interface; resultados executados têm os registros abaixo._

![Recorte da tabela: duas divergências do pedido PED-009-000](docs/images/workspace-desktop.png)

O recorte mostra **duas divergências do mesmo pedido**, entre **222 pedidos** do snapshot sintético. Duas divergências não significam dois pedidos afetados. A jornada registrada em **22/09/2026, 12:34 UTC** conferiu fontes, criou um dossiê, aprovou com outra conta e exportou a revisão. [Prova da jornada](docs/evidence/editorial-payment-20260922/payment-story.json) · [origem da captura](docs/evidence/screenshots-20260922.json).

No caso `PED-009-000`, as regras apontam incompatibilidade entre pagamento e snapshot e uma transição não observada dentro da cobertura. Elas não identificam a causa nem corrigem o sistema de origem. Fonte da observação: [conciliação registrada](docs/evidence/editorial-payment-20260922/payment-story.json), de **22/09/2026**. Contrato conferido em **22/09/2026**: [regras](backend/src/evidencedesk/reconciliation/rules.py).

1. Importe fontes e confira a cobertura do snapshot.
2. Investigue divergências, linha do tempo e originais.
3. Edite o dossiê ou solicite um rascunho opcional de IA.
4. Submeta a revisão para outra conta.
5. Exporte a versão aprovada com as fontes da decisão.

Fluxo conferido em **22/09/2026**: [jornada automatizada](frontend/e2e/payment-story.spec.ts) e [revisão/exportação](backend/src/evidencedesk/reviews/service.py). O percurso manual registrou **zero chamadas ao provedor** antes e depois, em **22/09/2026**; [consulta independente ao banco](docs/evidence/editorial-payment-20260922/provider-check.json). Isso não constitui avaliação por participantes humanos.

<a id="implementação"></a>
<a id="arquitetura-e-escolhas"></a>

## Arquitetura

```mermaid
flowchart TB
    UI[Next.js] --> API[FastAPI]
    API --> DB[(PostgreSQL e fila)]
    API --> Files[Arquivos privados]
    Worker[Worker Python] <--> DB
    Worker --> Files
    Worker --> Models[IA opcional]
```

O Compose separa API, worker, banco e frontend. A fila usa PostgreSQL; lease e identidade da execução protegem a publicação após perda de posse. A autorização combina organização, coleção e incidente; referências de resultados não dispensam a permissão atual. Fontes conferidas em **22/09/2026**: [Compose](infra/compose/compose.yaml), [jobs](backend/src/evidencedesk/jobs/service.py), [banco](backend/src/evidencedesk/database.py) e [fontes](backend/src/evidencedesk/evidence/service.py).

Os arquivos privados e o ledger de exclusões usam volumes locais. O adaptador Blob e a infraestrutura Azure são preparações separadas, com bloqueadores antes de uma operação entre hosts. [Armazenamento](backend/src/evidencedesk/evidence/storage.py), [ledger](backend/src/evidencedesk/deletion_ledger.py) e [validação de IaC](docs/evidence/azure-iac-validation.json), conferidos em **22/09/2026**. [Arquitetura completa](docs/architecture.md).

<a id="o-que-eu-implementei"></a>
<a id="stack"></a>

## Stack e decisões

<p>
  <img src="docs/stack/python.svg" alt="Python" width="64" height="64">
  <img src="docs/stack/fastapi.svg" alt="FastAPI" width="64" height="64">
  <img src="docs/stack/postgresql.svg" alt="PostgreSQL" width="64" height="64">
  <img src="docs/stack/typescript.svg" alt="TypeScript" width="64" height="64">
  <img src="docs/stack/react.svg" alt="React" width="64" height="64">
  <img src="docs/stack/nextjs.svg" alt="Next.js" width="64" height="64">
  <img src="docs/stack/docker.svg" alt="Docker" width="64" height="64">
</p>

| Componente                          | Papel e compromisso                                                                    |
| ----------------------------------- | -------------------------------------------------------------------------------------- |
| Python e FastAPI                    | Domínio, autorização, importação e operações assíncronas                               |
| PostgreSQL/pgvector                 | Dados, fila, isolamento e recuperação; o mesmo banco concentra essas responsabilidades |
| TypeScript, React e Next.js         | Interface para investigar, editar, revisar e exportar                                  |
| Docker Compose                      | Operação local com volumes próprios                                                    |
| Azure OpenAI, embeddings e reranker | Perfis opcionais; o fluxo manual e lexical não depende de geração                      |

Versões efetivamente fixadas: [backend](backend/pyproject.toml), [frontend](frontend/package.json) e [Compose](infra/compose/compose.yaml), conferidos em **22/09/2026**. O nome do deployment Azure é configuração do operador; não prova a identidade ou versão do modelo. [Contrato da integração](backend/src/evidencedesk/model_runtime/azure.py) e [documentação Microsoft](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints), consultados em **22/09/2026**.

Conciliação, revisão e geração têm responsabilidades separadas: uma citação válida estruturalmente ainda precisa sustentar o texto. O candidato treinado permanece sem promoção e sem adjudicação humana; esses estados constam no [protocolo](experiments/protocol.json) e no [pacote preparado](evals/human-review/package.json), conferidos em **22/09/2026**. [Model card](docs/model-card.md).

<a id="executar-e-verificar"></a>
<a id="rodar-localmente"></a>

## Executar localmente

Requisitos declarados pelo projeto: Docker com containers Linux, Compose **2.24.4+** e Python **3.11+** para a CLI do host. Fontes conferidas em **22/09/2026**: [operações](scripts/ops.py), [overlay com `!override`](infra/compose/integration.yaml) e [requisito oficial do Compose](https://docs.docker.com/reference/compose-file/merge/#replace-value). O build baixa dependências; a geração Azure exige configuração própria e pode ter cobrança do provedor.

```powershell
python scripts/ops.py config
python scripts/ops.py build
python scripts/ops.py start
python scripts/ops.py seed
```

Abra [localhost:3106](http://127.0.0.1:3106). Use `ana@aurora.demo` para investigar ou `bruno@aurora.demo` para revisar, com a senha pública da demonstração `EvidenceDesk-demo-2026!`. Contas e credenciais são sintéticas. [Seed](backend/src/evidencedesk/seed.py) e [publicação em loopback](infra/compose/compose.yaml), conferidos em **22/09/2026**.

```powershell
python scripts/ops.py stop
```

`stop` preserva os volumes conforme [implementação da CLI](scripts/ops.py), conferida em **22/09/2026**. [Instalação, Azure opcional e diagnóstico](docs/runbooks/local.md).

<a id="verificar-e-explorar"></a>

## Verificação e evidências

| Evidência                                                                                                        | Data e alcance                                                        |
| ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [Jornada de pagamento](docs/evidence/editorial-payment-20260922/payment-story.json)                              | 22/09/2026; UI/API reais, dados sintéticos e nenhuma avaliação humana |
| [Chamadas ao provedor](docs/evidence/editorial-payment-20260922/provider-check.json)                             | 22/09/2026; contagem no banco antes e depois da jornada manual        |
| [Reabertura após restauração](docs/evidence/restore-read-story/20260922T072246Z-492911fe/restore-execution.json) | 22/09/2026; execução histórica com identidade própria                 |
| [Scan da rodada editorial](docs/evidence/editorial-payment-security-20260922/summary.json)                       | 22/09/2026; imagens e base do scanner identificadas no registro       |

Conferência documental: **22/09/2026**. Esses registros sustentam as execuções identificadas, não um novo teste deste README. A lista de cenários e comandos está em [verificação](docs/verification.md) e [desenvolvimento](docs/development.md).

```powershell
python -m pip install --require-hashes -r scripts/requirements-docs.lock
python scripts/check_repository_docs.py
```

O [checker](scripts/check_repository_docs.py), conferido em **22/09/2026**, verifica caminhos e âncoras locais; não certifica conteúdo, sites externos ou qualidade semântica de respostas.

<a id="limites-e-manutenção"></a>
<a id="ia-e-escopo"></a>

## Limites e segurança

[Política de segurança e relato de vulnerabilidades](SECURITY.md) · [Modelo de ameaças](docs/threat-model.md) · [Scans das imagens](docs/publication-security.md).

A aplicação não corrige pedidos nem executa ferramentas de escrita nos sistemas de origem. As permissões são verificadas fora do modelo. Uma chamada com resultado desconhecido conserva sua reserva de tokens; a contabilidade é de tokens, não uma tabela monetária. Fontes conferidas em **22/09/2026**: [ferramentas](backend/src/evidencedesk/investigations/tools.py), [orçamento](backend/src/evidencedesk/investigations/budget.py) e [regras](backend/src/evidencedesk/reconciliation/rules.py).

O pacote humano reúne **60 casos de desenvolvimento em oito famílias**, marcado `prepared_not_executed`. Não há resultado de adjudicação nesse pacote; referências sintéticas não demonstram qualidade em incidentes reais. [Manifesto do pacote](evals/human-review/package.json), preparado em **22/09/2026** e conferido na mesma data. O conjunto reservado não foi usado nesta revisão.

A infraestrutura Azure permanece **não implantada por este projeto** nos registros disponíveis: `fmt`, `init` e `validate` locais não comprovam quota, SKU, rede ou capacidade regional. [Validação registrada](docs/evidence/azure-iac-validation.json) e [bloqueadores de rollout](docs/runbooks/azure-hosted.md), conferidos em **22/09/2026**. Scans e testes têm imagem e data próprias; não constituem garantia de ausência de falhas.

## Documentação

[Padrão compartilhado da documentação](docs/padrao-documentacao.md) · [Fontes e afirmações](docs/fontes-e-afirmacoes.md).

| Para consultar               | Documento                                                                                                                                                            |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Explorar o produto           | [Demo](docs/demo.md) · [casos e decisões](docs/problem-solution.md)                                                                                                  |
| Implementar e testar         | [Arquitetura](docs/architecture.md) · [API](docs/api-contract.md) · [dados](docs/data-contract.md) · [desenvolvimento](docs/development.md)                          |
| Operar e recuperar           | [Local](docs/runbooks/local.md) · [backup/restore](docs/runbooks/backup-restore.md) · [retenção](docs/runbooks/retention.md)                                         |
| Entender IA e orçamento      | [Model card](docs/model-card.md) · [modelos locais](docs/model-service.md) · [tokens](docs/token-budget.md)                                                          |
| Conferir riscos e resultados | [Política de segurança](SECURITY.md) · [threat model](docs/threat-model.md) · [publicação](docs/publication.md) · [fontes e afirmações](docs/fontes-e-afirmacoes.md) |
| Conferir imagens             | [Origem e reprodução](docs/screenshots.md)                                                                                                                           |

## Autor e licença

<p><a href="https://www.linkedin.com/in/arthur-joanes-6a2967373/"><img src="docs/contact/linkedin.svg" width="24" height="24" alt=""> <strong>Arthur Joanes no LinkedIn</strong></a></p>

[Licença MIT](LICENSE). Ícones da stack e LinkedIn: [Devicon, licença MIT](docs/stack/LICENSE.devicon). Licenças conferidas nos arquivos em **22/09/2026**.
