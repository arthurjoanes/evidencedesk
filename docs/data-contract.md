# Contrato dos dados e da proveniência

## Pacotes e limites

As entradas são um pacote fechado com manifesto `schema_version=1`, título, cobertura e até quarenta arquivos. Cada entrada declara ID, nome simples, tipo, MIME, quantidade de bytes e SHA-256. O limite é 10 MiB por arquivo e 40 MiB por pacote. Extensão/MIME e hash são validados; nome não pode conter caminho. Modelos Pydantic rejeitam campos desconhecidos dos registros estruturados.

O conteúdo extraído também tem orçamento por lote: no máximo 50.000 registros estruturados, 8 MiB de texto UTF-8 e 50.000 evidências derivadas. O worker aplica esses limites entre arquivos, antes de acumular o restante do lote; excesso resulta em `extraction_budget_exceeded`, sem publicação parcial. Parsing executa em processo com limite de memória/CPU/tempo; um arquivo comprimido internamente não recebe permissão para expandir sem limite apenas porque o upload era pequeno.

Fontes: [limites de extração](../backend/src/evidencedesk/ingestion/limits.py) e [contrato de importação](../backend/src/evidencedesk/ingestion/contracts.py), conferidas em **22/09/2026**.

| Entrada                 | Campos e interpretação                                                                                                                                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `events` JSONL          | `source_system`, `source_event_id`, `delivery_id?`, `order_reference?`, `event_type`, `occurred_at` nullable, `observed_at?`, `source_timezone`, `schema_version=1`, `payload`, `time_unknown_reason?`. Payload <=16 KiB. |
| `snapshots` CSV         | `source_system,snapshot_id,order_reference,status,as_of,source_timezone`. `as_of` representa o instante da fotografia do sistema de origem.                                                                               |
| `mappings` JSONL        | `source_system`, `source_order_reference`, `order_reference` canônico. Junção exige mapa explícito; sem similaridade de nomes ou IDs.                                                                                     |
| `document` TXT/MD/PDF   | Texto extraído e metadados de título, versão, sistema, linhagem documental, papel temporal e validade. PDF sem texto exige perfil OCR; o fluxo atual devolve erro explícito.                                              |
| `coverage` no manifesto | `source_system`, `from`, `to`, `status` complete/partial/unknown, `gaps`, `event_types`, `clock_uncertainty_ms?`. Desconhecimento não significa precisão perfeita ou coleta completa.                                     |

## Identidade e isolamento

Tenant, autor, coleção autorizada, evidence_id, instante de ingestão, hash do arquivo e localização são atribuídos pelo servidor. `source_tenant` é uma declaração do pacote; nunca concede autoridade. Identificadores de pedido iguais entre tenants são permitidos e não cruzam o isolamento.

Decisão de esquema: `user_id` é global, chave primária única em `users` (com `email` único), no [0001_foundation.sql](../backend/migrations/versions/0001_foundation.sql). A colisão de IDs iguais entre tenants que os testes de isolamento cobrem fica no nível de evidência e de pedido: as tabelas de domínio usam `PRIMARY KEY(tenant_id,id)`, então `evidence.id` se repete entre tenants (ver `test_cross_tenant_http_rls_connection_reuse_and_revoked_derived_data` em `backend/tests/integration/test_manual_workflow.py`) e o mesmo `order_reference` aparece nos dois tenants da demo (`PED-001-153` em `datasets/generated/aurora-01` e `horizonte-01`), não no nível de usuário. O isolamento entre organizações vem do RLS: a policy `tenant_isolation` filtra `tenant_id = current_setting('ed.tenant_id')` nas consultas de domínio.

## Tempo e reconciliação

Instantes precisam de fuso explícito. O recorte operacional usa ocorrência; quando ela é desconhecida, usa observação apenas para atribuir a evidência à janela, preservando a incerteza. Ambos nulos não atribuem o evento a uma janela. Data de upload não vira data do fato. Eventos recebidos tarde continuam atribuídos pela ocorrência. Snapshot usa `as_of`. Coverage é considerada somente no recorte correspondente.

Uma reentrega com mesmo ID lógico/conteúdo conta como observação adicional, não novo pagamento. Mesmo ID com conteúdo conflitante não vira fato canônico confiável. Regras não concluem uma transição ausente sem coleta completa do tipo/fonte/janela necessários. Divergência de relógio pode impedir conclusão de ordem temporal. A conciliação devolve revision, snapshot, coverage, janela, timeline e contagens determinísticas; não transfere aritmética para a geração.

O snapshot da aplicação congela a lista de evidências, mapas e cobertura publicados. Novos pacotes acumulam corpus na coleção e geram outro snapshot. Evidência derivada de conciliação aponta para snapshot e todos os IDs operacionais usados no recorte; não é inserida retroativamente em `snapshot_members`. Exclusão é uma exceção de disponibilidade auditada, não reescrita silenciosa da história.

Fontes: [regras de reconciliação](../backend/src/evidencedesk/reconciliation/rules.py) e [contratos temporais](../backend/src/evidencedesk/reconciliation/contracts.py), conferidas em **22/09/2026**.

## Metadados documentais

Documentos têm papéis diferentes: `applicable_procedure` exige validade sobreposta à janela; `historical_artifact` é fonte histórica; `retrospective_context` é análise posterior. O sistema preserva o papel no contexto para evitar transformar uma explicação posterior em evidência de que a equipe já a conhecia no momento do incidente.

Na entrada documental, os campos interpretados de `metadata` são validados: título (até 300 caracteres), versão, sistema e linhagem são textos; papel temporal aceita os três valores acima; datas precisam representar instantes com fuso e o fim deve ser posterior ao início. Campos extras continuam preservados no manifesto e na entrada original. Um pacote antigo ainda pendente também é validado pelo worker: metadados inválidos produzem `invalid_document_metadata`, sem snapshot parcial.

Os mesmos bytes e a mesma identidade de trecho podem ser reimportados com metadados equivalentes, incluindo datas com offsets diferentes que representam o mesmo instante. Divergência de título, versão, sistema, linhagem, papel ou validade gera `document_metadata_conflict` e rejeita o pacote inteiro, inclusive quando as duas entradas conflitantes estão no próprio lote. O snapshot anterior e suas evidências permanecem intactos. Reclassificar uma fonte já publicada exige um fluxo próprio de versionamento, ainda não implementado; a importação não altera silenciosamente sua interpretação.

Fontes: [metadados de entrada](../backend/src/evidencedesk/ingestion/contracts.py) e [serviço de importação](../backend/src/evidencedesk/ingestion/service.py), conferidas em **22/09/2026**.

## Divisão em trechos

Novas importações documentais usam parser `text-pdf-v2` e chunk policy `utf8-bytes-352-v2`: até 352 bytes UTF-8 por trecho, preferindo quebra de linha quando possível, preservando todos os caracteres e offsets por página. O registro declara `canonical_bytes` e `token_count=null`. É uma política conservadora offline, não um tokenizer nem garantia universal de tokens após normalização Unicode. O encoder/reranker verificam limites reais e rejeitam entradas grandes com 422 sem retry. Cada fonte conserva hash do arquivo original, página, linhas e char_start/char_end do texto canônico extraído; offsets do PDF são sobre o texto extraído, não sobre bytes do PDF.

Identidades documentais incluem a revisão da divisão e os offsets; v2 não reutiliza IDs de parser-v1. Snapshot antigo continua antigo e pode exigir reimportação para indexar. Modelos não truncam fontes do produto silenciosamente. A escolha de trechos para contexto elimina trechos inteiros por orçamento e registra os efetivamente enviados no manifesto; não os recorta pelo trecho esperado do gold.

Fontes: [política de trechos](../backend/src/evidencedesk/retrieval/chunking.py) e [contratos do cliente de modelos](../backend/src/evidencedesk/retrieval/http_client.py), conferidas em **22/09/2026**.

## Separação dos conjuntos

Coleções de dados são separadas:

- `datasets/generated`: demo sintética, dois tenants, trinta incidentes, seis pacotes e noventa documentos. Usada apenas para exercitar o produto.
- `experiments/data`: pares de treino/dev e linhagens descritos no protocolo. Nunca importados como documentos da demo. Rótulos ficam fora do contexto de inferência.
- `evals`: 120 grupos, sessenta dev e sessenta reservados. O reservado cobre novas instâncias e famílias separadas. Qualquer inspeção destinada a corrigir o sistema aposenta o conjunto como avaliação não vista.

Fontes dos tamanhos dos conjuntos: [gerador da demo](../datasets/generate.py), [protocolo de treino](../experiments/protocol.json) e [manifesto de evals](../evals/data/manifest.json), conferidos em **22/09/2026**. São conjuntos sintéticos; quantidade não implica validação humana.

Mudanças em regras, parser, embeddings ou corpus exigem novas revisões e comparação reproduzível. O [manifesto de modelos](../model-manifest.json) aponta os hashes medidos; [datasets/README.md](../datasets/README.md) contém o comando do gerador, e [evals/README.md](../evals/README.md) define denominadores e gates.

Fontes desta seção, conferidas em **22/09/2026**: [0001_foundation.sql](../backend/migrations/versions/0001_foundation.sql) · [model-manifest.json](../model-manifest.json).
