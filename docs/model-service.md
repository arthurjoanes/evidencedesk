# Inferência local isolada

O core FastAPI não instala Torch. O serviço privado `models:8090` carrega E5 e o reranker base, com uma inferência por vez e sem banco, credenciais Azure ou execução de ferramentas. O treinamento usa outro processo. O candidato treinado não foi promovido.

## Cliente e rotas

`RemoteModels(httpx.Client(base_url="http://models:8090", trust_env=False), token=...)` implementa `encode_query(query)`, `encode_passages(passages)` e `score_passages(query, passages)`. Quem cria o cliente fecha o pool. O construtor valida o endereço interno fixo; respostas precisam corresponder à revisão solicitada, dimensão, quantidade e normalização. Não há redirecionamentos nem retry oculto. Erros expõem somente `ModelServiceError.code` e `retryable`.

| Rota                  | Entrada                                                                     | Saída                                                    |
| --------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------- |
| `POST /v1/embeddings` | `revision`, `task` query/passage, `texts` (uma query ou até oito passagens) | revisão, dimensão 384, vetores na ordem recebida         |
| `POST /v1/rerank`     | `revision`, `query`, `passages` (até vinte)                                 | revisão, scores na ordem recebida                        |
| `GET /healthz`        | nenhuma                                                                     | disponibilidade, revisões e dispositivo                  |
| `GET /metrics`        | bearer interno                                                              | contadores por operação/desfecho e histograma de duração |

## Limites de entrada

O [serviço HTTP](../backend/src/evidencedesk/retrieval/model_service.py) autentica o bearer antes de interpretar o corpo. O limite de 128.000 bytes também vale para corpo transmitido em partes. Campos extras, incluindo tenant ou endereço de fonte, são rejeitados. O [cliente privado](../backend/src/evidencedesk/retrieval/http_client.py) tem connect/write de dois segundos, pool de um segundo e read de quinze segundos; o servidor rejeita simultaneidade com 503 em vez de criar fila sem limite. Entradas E5 e pares de reranking acima de 512 tokens são recusados: rechunking é necessário, nunca corte orientado pelo gold.

O erro `evidence_requires_rechunking` retorna 422 sem retry automático; query E5 longa retorna `model_query_too_long`. Novas importações usam política offline <=352 bytes UTF-8, com parser/IDs v2. O campo token_count continua nulo até medição real; bytes não garantem tokens universais após normalização. Fontes antigas continuam imutáveis e podem exigir nova importação. Validação offline com tokenizers pinados sobre os noventa documentos demo produziu 180 chunks, máximo 80 tokens E5 e 97 no par de reranking para a pergunta padrão; [relatório](../experiments/reports/chunk-policy-tokenizers.json). Isso não é benchmark de qualidade e não acessa gold reservado.

## Autorização e recuperação

O core autoriza tenant, coleção, incidente e snapshot antes de enviar texto. O modelo recebe apenas textos selecionados, sem poder buscar outros. É necessário revalidar autorização depois da inferência e antes de publicação. Spans do cliente registram operação, revisão e desfecho; métricas não usam IDs de pedido, documentos, conteúdo ou segredos.

`index_snapshot(engine, actor, snapshot_id, encoder, *, embedding_revision=EMBEDDING_REVISION)` devolve `IndexResult(evidence_snapshot_id, embedding_revision, indexed_now, total_documents, complete)`. `RemoteModels` fornece `batch_size=8` e `dimensions=384`. A indexação abre transações curtas, libera o pool enquanto codifica e verifica política, grants, hash, texto e snapshot novamente antes de escrever. A mesma revisão retoma lotes pendentes. Uma revisão diferente exige uma nova versão de corpus/evidências; não se sobrescreve o vetor anterior. Busca vetorial rejeita índice parcial.

`search_evidence(connection, actor, incident_id, snapshot_id, query, mode="lexical", limit=8, *, purpose=None, query_embedding=None, embedding_revision=None)` aplica ACL e validade antes de rankear. Faça `encode_query` antes de abrir a conexão. Para reranking, recupere até vinte candidatos, feche a transação e execute `rerank_evidence(query, evidence, remote_models, limit=8)`; o limite final é de oito. A função retorna os mesmos `ContextEvidence`, com localizadores e papéis temporais preservados.

O planner `lexical-v2` normaliza português pelo PostgreSQL, preserva a primeira ocorrência de até dezesseis lexemas distintos e os une com OR. A pergunta original permanece no run. A versão anterior aplicava AND à pergunta inteira e encontrou zero documentos no experimento sintético; os dois resultados permanecem no relatório. Mudança de planner/revisão deve integrar a configuração congelada da investigação.

## Perfis de execução

No laboratório, `docker compose -f experiments/compose.yaml --profile serving up -d --wait models` inicia o serviço. Usa a imagem ML separada, UID 10001, pesos em `model_cache` somente leitura, modo offline, GPU, duas CPUs e 3 GiB de RAM. Não publica porta. `ED_MODEL_SERVICE_TOKEN` precisa de pelo menos 24 caracteres; o fallback de compose é exclusivamente uma credencial pública de demonstração local. Configure outro valor em qualquer implantação. `ED_MODEL_DEVICE` é explícito; não há fallback silencioso de GPU para CPU.

No compose principal, o serviço pertence ao perfil `ml`, não recebe credenciais Azure/DB e o token padrão é vazio. A API retorna capability de indexação pelo token configurado; isso não é prova de readiness. O usuário pode continuar no modo lexical mesmo sem serviço ML.

## Resultados registrados

Smoke HTTP real em 21/09/2026: embeddings de query e duas passagens, reranking base, autenticação de métricas e readiness passaram em 1,17 segundo. O serviço carregado ocupou aproximadamente 2,02 GiB; o container tem teto de 3 GiB. São evidências funcionais, não teste de capacidade. Para repetir: `docker compose -f experiments/compose.yaml run --rm lab python experiments/smoke_model_service.py`.

Rebuild final: o compose do laboratório usa por padrão `pf-evidencedesk-ml:torch2.14-cu130-locked-20260921` (`ED_ML_IMAGE` permite override explícito). A instalação do lock final e os 116 pacotes foram conferidos; a [smoke na nova imagem](../experiments/reports/model-service-smoke-locked.json) repetiu os contratos reais com as mesmas revisões/dimensão, sem substituir o relatório anterior. [Image IDs, SHA do lock e limites observados](../experiments/reports/ml-final-build.json). O mount do serviço aponta apenas `backend/src/evidencedesk` para `/app/evidencedesk`, evitando metadados `.egg-info` do core. O serviço foi parado após a validação para liberar recursos. Não houve nova avaliação de qualidade nem scan CVE da imagem ML nesta etapa.
