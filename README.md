# EvidenceDesk

Um pagamento foi confirmado, mas o pedido continua pendente. O EvidenceDesk ajuda um analista a conferir eventos, snapshots e procedimentos, formular uma hipótese com fontes e submeter uma conclusão a outro revisor.

O produto é uma bancada de investigação, com aplicação Next.js, API e workers Python. A conciliação é determinística. A IA produz um rascunho citado; não aprova a própria resposta nem executa pagamentos ou reprocessamentos.

![Incidente e leitor de evidência no ambiente de teste isolado](frontend/artifacts/review-final-2026-09-21/screenshots/workspace-desktop.png)

## Executar localmente

Pré-requisitos: Docker Desktop em Linux containers, Compose 2.24.4+ e Python 3.11+. Na raiz deste repositório:

```powershell
python scripts/ops.py config
python scripts/ops.py build
python scripts/ops.py start
python scripts/ops.py seed
python scripts/ops.py status
```

Abra [a aplicação](http://127.0.0.1:3106). API: [8106](http://127.0.0.1:8106/docs). O seed é explícito, sintético e repetível. Os defaults são somente para demonstração em loopback.

| Organização | Analista | Revisor |
| --- | --- | --- |
| Aurora | `ana@aurora.demo` | `bruno@aurora.demo` |
| Horizonte | `carla@horizonte.demo` | `diego@horizonte.demo` |

Senha fictícia: `EvidenceDesk-demo-2026!`. Há também `admin@aurora.demo` e `admin@horizonte.demo` para administração autorizada. IDs iguais nos dois tenants exercitam isolamento; não representam empresas ou pessoas reais.

Sem chave Azure, investigação manual, importação, conciliação, revisão e exportação continuam funcionando. Para configurar a inferência no Windows, execute `pwsh -NoProfile -File scripts/azure_runtime.ps1 -Action configure`; a entrada é oculta e o segredo protegido por DPAPI fica fora do repositório. Depois use `-Action start`. Esse helper preserva a credencial ao recriar API/worker; um `ops.py start` que removeria uma credencial já configurada é recusado antes de alterar os serviços. Nenhum comando de build faz inferência.

`python scripts/ops.py stop` preserva os volumes. Configuração, recursos, portas e recuperação estão no [runbook local](docs/runbooks/local.md). Modelos E5/reranker são um perfil separado; instalação de pesos e execução real estão documentadas em [experiments](experiments/README.md).

## O que foi executado

- Jornada manual completa com PostgreSQL real: importar, conferir fonte/PDF, editar revisão, tratar conflito, obter aprovação de outra conta e exportar.
- Uma investigação Azure real com Luna: 1.166 tokens de entrada e 784 de saída, três alegações em rascunho. JSON e manifesto tiveram hashes verificados; a mesma revisão foi reaberta após reinício sem nova geração. Isso comprova integração e persistência, não qualidade semântica aprovada.
- E5, busca vetorial/RRF e reranker executados em corpus sintético; um experimento supervisionado rodou na GPU local. Os resultados positivos e negativos estão preservados. O candidato não foi promovido sem o gate humano.
- Testes de RLS/ACL, cancelamento, perda de lease, concorrência de upload, quotas, exclusão e restauração. Logs e traces chegaram ao laboratório OTel; um alerta disparou e resolveu.

Consulte a [revisão integrada mais recente](docs/review-integrated-followup-2026-09-21.md), a [matriz de verificação](docs/verification.md), os [experimentos](experiments/README.md) e os [limites atuais](docs/progress.md). Os números dos ensaios de capacidade são de laboratório; não provam disponibilidade de produção nem escalabilidade entre hosts.

## Onde estudar

| Decisão | Código e explicação |
| --- | --- |
| Eventos, reentregas, clocks e divergências | [reconciliation](backend/src/evidencedesk/reconciliation/rules.py) |
| Autorização e dados derivados | [identity](backend/src/evidencedesk/identity/service.py), [reviews](backend/src/evidencedesk/reviews/service.py), [ameaças](docs/threat-model.md) |
| Ferramentas com autoridade limitada | [tools](backend/src/evidencedesk/investigations/tools.py) |
| Jobs, lease e publicação | [jobs](backend/src/evidencedesk/jobs/service.py) |
| Azure, schema, versões e orçamento | [model_runtime](backend/src/evidencedesk/model_runtime), [budget](backend/src/evidencedesk/investigations/budget.py) |
| Bancada, leitor e revisão | [frontend](frontend/src/features), [revisão de código](docs/clean-code-review.md) |
| Exclusão, GC e quota por arquivo | [retention](backend/src/evidencedesk/retention), [runbook](docs/runbooks/retention.md) |

[Arquitetura](docs/architecture.md) · [API](docs/api-contract.md) · [demo de cinco minutos](docs/demo.md) · [guia de entrevista](docs/interview-guide.md) · [revisão por especialidade](docs/specialty-review.md).

## Limites deliberados

Os dados e referências de avaliação são sintéticos. Suporte de citações exige adjudicação humana; uma fonte existente não prova uma frase. O holdout não serve para ajustar continuamente o sistema. Custos monetários Azure permanecem sem precificação porque não há tabela/região comercial configurada.

A aplicação usa Azure OpenAI a partir do laboratório local. O restante do fullstack ainda não está hospedado no Azure. IaC/Blob são preparação de perfil: identidade, rede, ledger e recuperação cloud precisam de validação antes de rollout. OCR, kind, MCP e LLM gerativo local não são habilidades demonstradas por um diretório vazio; seu estado está explícito em [arquitetura](docs/architecture.md).

O [scan das imagens](docs/security-image-review-2026-09-21.md) continua reprovando o gate HIGH/CRITICAL por achados herdados da distribuição Linux. As correções disponíveis do frontend foram aplicadas e verificadas; os restantes têm triagem explícita, sem supressões. O projeto é entregue para demonstração local, sem liberação de produção pelo gate.

Repositório local, sem push nem histórico profissional inventado. A ajuda de IA não é ocultada; a qualidade é avaliada por comportamento, clareza e evidência de manutenção.

## Technical summary

EvidenceDesk is a multi-tenant incident investigation workbench built with Next.js/TypeScript and a modular FastAPI/PostgreSQL backend. Deterministic reconciliation, immutable evidence snapshots, bounded retrieval tools, Azure structured generation, human review, durable jobs, RLS and fencing protect the investigation lifecycle. Local experiments and operational reports distinguish simulated transports, real model execution, measured failures and unvalidated production claims.
