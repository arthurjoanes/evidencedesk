# Revisão de engenharia de IA e autorização

Revisão de código e testes em 21/09/2026. Não substitui auditoria externa, revisão semântica humana ou teste de produção. O candidato treinado permanece fora do serviço.

| Achado | Correção e evidência | Limite residual |
|---|---|---|
| Prazo das ferramentas reiniciava ao construir outro executor | O primeiro `tool.invoked` estabelece 120 segundos pelo relógio do banco; tentativas novas herdam esse prazo. Teste muda o fencing token e recria o executor. | Uma operação síncrona em andamento pode encerrar após o limite; sua saída é rejeitada. Timeout de rede e deadline do job continuam separados. |
| Divisão em 1.800 caracteres podia ultrapassar tokens reais | Novos documentos usam `utf8-bytes-352-v2`, preservam texto e offsets e recebem novas identidades. O serviço verifica o tokenizer real e devolve 422 sem retry quando necessário. | Bytes não são tokens. Normalização Unicode pode expandir texto; perguntas longas e pares query/documento ainda podem exceder o limite. Fontes antigas não são alteradas. |
| Contexto recuperado não era conferido individualmente imediatamente antes do despacho | Cada fonte efetivamente enviada é resolvida novamente, incluindo dependências do agregado; texto, título, tipo, papel temporal e validade devem corresponder. A admissão verifica novamente política e lease. O manifesto registra IDs e SHA-256 do texto enviado. | Revogação após a admissão não desfaz texto já enviado ao provedor. Publicação é bloqueada e uso continua contabilizado. |
| Capability de indexação não era explícita | GET/POST do índice incluem `indexing_enabled` e `disabled_reason`; modo lexical pode indexar quando o token interno existe. | Configuração não demonstra disponibilidade do serviço. O job reporta falhas de rede/modelo separadamente. |
| Fixture de geração dependia do provider padrão do ambiente | `prepare_run` define provider Azure explicitamente e usa transporte simulado. | Teste de contrato não mede qualidade do Azure; não há chamada paga nesses testes. |

Os limites de oito chamadas e 64.000 bytes são duráveis: consultas ao audit incluem todas as tentativas, e a admissão fica registrada antes de executar. Falhas consomem chamadas. Saída acima do limite não chega ao chamador. Locks de política/lease serializam a admissão e a publicação; a memória do worker não é a fonte da quota.

Retrieval aplica tenant, grants de coleção, associação ao incidente, snapshot, tombstone e validade de procedimento antes do ranking SQL. A busca vetorial é exata dentro do conjunto autorizado, sem ANN global seguido de filtro Python. O contexto histórico e retrospectivo continua identificado; a presença de uma fonte não prova causalidade. RRF e reranking usam apenas candidatos recuperados, sem inserir um positivo ausente por consulta aos rótulos.

Indexação libera a conexão durante inferência. Cada lote verifica novamente lease/fencing/cancelamento, política, grants, hash, texto e pertença ao snapshot antes de gravar. Cancelamento ou revogação durante o encoder não publica o lote. Índice parcial não é apresentado como pronto para busca vetorial. Vetores de outra revisão não são sobrescritos. Um job terminal não é reiniciado pelo mesmo POST: reimportação/versionamento ou operação administrativa explícita são necessários; não há botão de recuperação implementado.

Na publicação, revisão/claims resolvem referências novamente e o lease precisa continuar válido. Contagens e impacto vêm da conciliação determinística; a geração fornece síntese qualitativa. Citações válidas estruturalmente não equivalem a suporte semântico. Exclusão invalida derivados por snapshot e a retenção trata os artefatos, inclusive tentativas sem publicação. O controle de acesso assume que mutações administrativas usam o protocolo de lock e incremento da revisão; alteração manual fora desse protocolo não é uma API suportada.

O release congela deployment, endpoint permitido, instruções e hash, schema, limites, planner lexical, perfil de retrieval e revisões E5/reranker. O endpoint e as identidades nunca vêm de argumentos do modelo. A reprodução também precisa dos hashes de corpus, imagem/código, parser e regras: o JSON de release não é um congelamento do binário inteiro. Mudanças em planner de perguntas, regra ou parser exigem versionamento e reavaliação, mesmo quando os pesos permanecem iguais.

Verificação desta revisão: 71 testes unitários/de métricas de chunks/runtime/model service/retrieval/release/avaliação, 16 testes de integração de ferramentas/índice/workflow/orçamento e mypy de 14 módulos passaram. Integrações usam tenants temporários na base descartável, nenhuma chamada Azure. Testes incluem cancelamento/revogação durante inferência, alteração de fonte antes de pagar, uso contabilizado sem publicação, orçamento mensal, isolamento do ledger e prazo/bytes entre execuções. Esses números descrevem a rodada da revisão, não toda a suíte do projeto.

Gates de qualidade permanecem separados:

O [pacote local de revisão semântica](../evals/human-review/README.md) torna o próximo passo executável: casos dev e fontes identificados, rubrica por alegação e formulários para rodada/resposta. Seus campos humanos permanecem vazios. Preparar esse material não promove o candidato nem altera as métricas históricas.

- **Executado:** PostgreSQL FTS, E5, RRF, reranker base/candidato, treino GPU, smoke HTTP privada e testes determinísticos. Resultados e hashes estão em [experiments/reports](../experiments/reports/index.json).
- **Não aprovado:** promoção do candidato. A primeira rodada falhou latência; a segunda passou a medida observada, com candidatos diferentes. Ambas permanecem no relatório.
- **Pendente:** adjudicação humana de rótulos/respostas, regressões semânticas, validade temporal de interpretações, abstenção e robustez contra instruções em fontes. Testes conhecidos de isolamento/contratos não certificam segurança universal de modelos.
- **Não utilizado:** conjunto reservado. Não foi aberto para corrigir esta implementação. Uma execução final exige release/corpus congelados e ledger de uso; depois de inspeção para ajuste, o conjunto deixa de ser não visto.
- **Nova avaliação necessária:** chunks v2 mudam unidades documentais e candidatos. Os ganhos sobre 124 documentos do laboratório não são automaticamente transferíveis ao corpus reimportado com v2.

Referências técnicas, licenças, revisões e limitações dos modelos: [model card](model-card.md), [manifesto](../model-manifest.json), [contrato de dados](data-contract.md), [protocolo de avaliação](../evals/README.md), [experimento](../experiments/README.md). Nenhum modelo recebeu autorização para executar comandos, acessar URLs ou decidir grants.

Fechamento de reprodução: a receita final da imagem ML foi reconstruída com o lock, comparada em 116 pacotes e exercitada por HTTP real. [Evidência](../experiments/reports/ml-final-build.json). Isso fecha a pendência de execução do Dockerfile final; não altera métricas de ranking nem promove candidato. Não foi realizado scan de vulnerabilidades da imagem ML nesta etapa.
