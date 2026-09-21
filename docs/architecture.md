# Arquitetura de implementação

Estado em 21/09/2026: núcleo implementado e verificado no laboratório local. Esta decisão preserva o escopo em [specification.md](specification.md) e [arquitetura de origem](source/14-ARQUITETURA-EVIDENCEDESK.md). Evidências e gates pendentes estão em [verification.md](verification.md); aprovação humana de qualidade, liberação de produção pelo scan e hospedagem Azure não são declaradas.

## Problema e fronteiras

Analistas investigam pedidos presos entre pagamento, estoque e entrega. Fontes têm relógios, cobertura e revisões diferentes. Conciliação determinística produz divergências; IA propõe hipóteses citadas; outro usuário decide sobre uma revisão imutável. Não há remediação automática. O mesmo fluxo de evidências/revisão/exportação funciona sem gerador.

## Decisões no ambiente real

- Repositório independente nesta subpasta, sem dependências nos cinco projetos irmãos. Host Windows, Python 3.11.9, Node 24.19.0/npm 11.17.0. Contêineres fornecem o runtime Linux; recursos/portas estão em [environment.md](environment.md).
- Monólito modular Python/FastAPI, SQLAlchemy e Alembic. PostgreSQL/pgvector guarda conteúdo, snapshots, sessões, fila e auditoria. API e workers são processos separados. O pool não permanece adquirido durante parsing, modelo ou armazenamento remoto.
- Next.js App Router/React/TypeScript compõe a bancada. Mesma origem por proxy /api/v1 para FastAPI; regras e autorização no servidor Python. Recursos interativos limitados por feature, TanStack Query por contexto, sem cache público de dados autenticados.
- Armazenamento privado local compartilhado por API/workers. Arquivos identificados por chaves relativas derivadas pelo servidor; Azure Blob SDK é a alternativa de hospedagem. Objeto confirmado antes de publicação transacional; órfãos recolhidos apenas após período seguro.
- Azure OpenAI v1 Responses, deployment gpt-5.6-luna, é o gerador principal. Sem credencial de runtime, a função informa indisponibilidade e o fluxo manual permanece íntegro. Não copiar a chave da conversa para o repositório. store=false/background=false e persistência própria. Embeddings/reranker independentes, com revisões fixadas.
- RLS em todas as tabelas de conteúdo por tenant; aplicação sem owner/superuser/BYPASSRLS. Identidade/sessões e registro operacional mínimo permitem resolver contexto antes de acessar conteúdo. ACL de coleção e incidente é validada explicitamente além do RLS. Migrações têm credencial separada.
- Jobs PostgreSQL com aquisição SKIP LOCKED, lease/relógio do banco, fencing e política compartilhada. Conclusão e revogação serializam no registro de política. API admite e persiste a intenção na mesma transação; worker não publica resultado sem lease, autorização e ausência de cancelamento.
- OTel/logs JSON/métricas desde a primeira jornada. Stack local de observabilidade é um perfil separado; Azure Monitor no perfil hospedado, sem duplicação padrão. Métricas operacionais não substituem auditoria ou resultados persistidos.

## Contratos que não podem se perder

Mesmo identificador entre tenants nunca permite compartilhamento de dados. occurred_at, observed_at, ingested_at e snapshot.as_of não são intercambiáveis. Um evento lógico pode ter múltiplas observações/entregas; isso não comprova pagamento duplicado. Corpus/snapshot são fixos durante exploração/run, mas permissão é sempre atual. Resultado aprovado é imutável; nova edição cria revisão e exige comparação com base_revision. Autor não aprova a própria submissão. Citação existe em fonte/versionamento autorizado e é validada pelo servidor; isso não certifica suporte semântico.

## Composição visual

Bancada editorial clara: grafite, papel e seleção azul contida. Fila comparável; cabeçalho de incidente compacto; divergências/timeline/dossiê/fontes com leitor contextual. Componentes de domínio e tokens desde a primeira fatia. Desktop lado a lado e navegação sequencial em 320/768px. PDF com texto canônico e lazy loading. Sem landing page, números inventados ou ocultação de proveniência da IA.

## Alternativas

Busca lexical + dossiê manual é a primeira baseline executável. SQLite não substitui as garantias de RLS, locks e concorrência do PostgreSQL. Broker, microserviços e framework de agentes acrescentariam fontes de verdade e complexidade desnecessárias agora. Serviços extras só entram com necessidade medida; o núcleo completo continua sendo o definido na especificação.

## Ordem de verificação

Cada incremento mantém o plano integral e registra implementado/validado/pendente. Primeiro jornada manual real; depois ingestão/fila/ACL e falhas concorrentes; retrieval/modelo; avaliações/experimento; operação/carga; revisão visual e de código. Aprovação humana de avaliações semânticas não será simulada por outro agente.

## Decisões consolidadas na implementação

- A baseline ativa é lexical, com planejamento de uma pergunta preservada. Até três subquestões são permitidas pelo contrato; expansão automática não foi promovida sem evidência de ganho. Ferramentas internas são funções explícitas, não um framework de agentes nem uma cadeia de raciocínio privado persistida.
- Perfil de retrieval e revisões E5/reranker ficam congelados junto da geração. Índice incompleto não vira busca híbrida parcialmente válida. Jobs de indexação usam a fila existente e validam lease/ACL antes de publicar cada lote; modelo/rede ficam fora da conexão DB.
- E5 e reranker rodam em serviço privado separado, com versões fixadas e token próprio. API/worker não carregam Torch; weights/cache estão em volume do perfil ML. O candidato treinado fica isolado, sem promoção automática.
- A listagem usa cache pequeno de contagens/cobertura por tenant/snapshot/janela/política, limite de memória e single-flight. Não cacheia autorização, último dossiê ou run. Medição inicial encontrou saturação de pool; o relatório mantém o antes/depois.
- Quota de importação tem ownership por entrada e liberação CAS após remoção. Documentos e dossiês não expiram por idade; temporários/exports/progresso/auditoria seguem o [runbook de retenção](runbooks/retention.md).
- Tokens são contabilizados por mês UTC. Consumo conhecido pertence ao mês da chamada; reserva desconhecida antiga continua comprometendo a capacidade futura. Uma tentativa expirada depois do provedor não chama novamente, inclusive quando uso já foi reportado.
- Antes do despacho, a configuração atual de geração é conferida novamente, antes da reserva de tokens. Uma release congelada não contorna a desativação operacional do provedor ou a ausência da credencial.
- Login reserva admissão global no PostgreSQL antes de criar uma chave de e-mail; mantém o limite por conta, expira chaves em lotes e limita hashes Argon2 simultâneos por processo. Os defaults e os limites contra DoS estão na [revisão do backend](review-backend-2026-09-21.md); a proteção de borda permanece necessária para publicação externa.
- Listagens de incidentes/importações usam criação decrescente com desempate por ID imutável e cursor assinado. A lista de fontes operacionais aplica o mesmo fallback temporal da conciliação; documentos permanecem contexto documental.
- Objetos e ledger locais são duráveis nos volumes deste host. AzureBlobStorage possui contrato isolado e testes de SDK simulados; não é selecionado pelo core. O rollout hospedado depende de I/O remoto/quarentena e ledger compatíveis, sem segurar pool durante rede.

## Perfis e estado

| Perfil | Estado demonstrado | Limite |
| --- | --- | --- |
| offline-manual/core local | Jornada real completa com DB/arquivos e frontend | Defaults apenas loopback; sem garantia de HA. |
| core com Azure OpenAI | Uma geração real, hashes e reabertura após restart | Sem gate semântico humano ou precificação monetária. |
| observability | OTel/Prometheus/Loki/Tempo/Grafana/Alertmanager reais | SLO de30 dias continua objetivo, não resultado do laboratório. |
| models/experiments | Embeddings, reranker, GPU e treino reais | Pesos exigem setup explícito; candidato não promovido. |
| scale-lab | 1/2 APIs e workers, mesma massa e relatórios preservados | Réplicas compartilham host/volume; sem prova entre hosts. |
| Azure hospedado | Preparação IaC e adaptador privado | Não provisionado; identidade/rede/Monitor/GC/ledger exigem validação. |
| OCR | Estado requires_ocr implementado | Extração OCR/tabelas digitalizadas não executada. |
| kind, MCP, LLM generativo local/vLLM | Extensões não implementadas nesta entrega | Não necessárias ao núcleo; GPU comprovada para embeddings/reranker/treino, não para vLLM. |

Essas extensões permanecem declaradas como pendência de escopo, conforme a seção14 da especificação. Não há manifests vazios apresentados como demonstração de habilidade.
