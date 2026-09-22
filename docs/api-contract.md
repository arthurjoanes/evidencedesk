# Contrato HTTP v1 — implementação compartilhada

Base `/api/v1`. JSON usa snake_case e ISO8601 UTC. IDs são strings opacas. A API aplica as regras, contagens e permissões. Esquema resumido do erro: `{error:{code,message,request_id,retryable,field_errors?}}`; `field_errors` é um mapa de listas de mensagens. Respostas privadas usam `Cache-Control: no-store`. As estruturas resumidas abaixo são notação de contrato; campos sem valores não são corpos JSON prontos para envio.

## Coleções acessíveis

`GET /api/v1/collections?limit=50&cursor=...` retorna `items`, `next_cursor` e `total: null`. `limit` aceita de 1 a 100. A ordem é por nome e ID; `next_cursor` é nulo ao terminar a listagem. O cursor assinado pertence ao usuário e tenant autenticados. Cada página revalida as permissões atuais, e nomes iguais têm desempate pelo ID.

## Identidade

`POST /auth/login` `{email,password}` → Session, cookie HttpOnly ed_session. `GET /auth/session` → Session; sem sessão 401. `POST /auth/logout` →204. Mutações autenticadas exigem Origin permitido e X-CSRF-Token, inclusive logout. Login exige Origin permitido. SameSite=lax; Secure no HTTPS. Front encaminha cookie/Origin, nunca credencial Azure.

Session = `{user:{id,name,role},tenant:{id,name},csrf_token,expires_at,permissions:string[],runtime:{generation_enabled,provider,model_display_name,disabled_reason:null|string}}`.

Papéis tenant_admin/analyst/reviewer. Demo pública local: ana@aurora.demo, bruno@aurora.demo, carla@horizonte.demo, diego@horizonte.demo. Senha fictícia de demo `EvidenceDesk-demo-2026!`, apenas seed explícito de laboratório. Ana/Carla analyst; Bruno/Diego reviewer. Contas admin de seed separadas. UI não simula troca de papel: sair/entrar com outro usuário.

## Listas e incidentes

Page<T> = `{items:T[],next_cursor:string|null,total:number|null,evidence_snapshot_id?:string}`. limit padrão 30 máximo 100. Cursor vinculado ao usuário/tenant, filtros, recurso e snapshot, rejeitado 409 se contexto incompatível. Filtros de lista: q, status, cursor, limit. Ordem explícita em contrato por endpoint; não ordenar só a página como se fosse conjunto global.

`GET /collections` → Page de `{id,name,description,active_snapshot_id:null|string}`.

`POST /incidents` `{title,collection_id,window:{from,to,time_zone},description?}` →201 Incident. `GET /incidents` → Page<Incident>. `GET /incidents/{id}` → Incident.

Incident = `{id,title,status,description,collection_id,window:{from,to,time_zone},created_at,updated_at,evidence_snapshot_id,available_snapshots:[{id,published_at}],coverage:[{source_system,status,from,to,gaps:string[]}],counts:{orders,divergences},latest_run:RunSummary|null,dossier_id:null|string,permissions:string[]}`. status=open|in_review|resolved; regras de revisão decidem resolução, não inferência automática.

`GET /incidents/{id}/timeline?evidence_snapshot_id=&order_reference=&cursor=&limit=` → Page<TimelineRow> com coverage e ordering='occurred_at_nulls_last'. TimelineRow={id,evidence_id,order_reference:null|string,source_system,event_type,occurred_at:null|string,observed_at:null|string,ingested_at,temporal_quality,delivery_count}. Não substituir datas ausentes.

`GET /incidents/{id}/reconciliation?evidence_snapshot_id=&order_reference=&cursor=&limit=` → Page<Divergence> com coverage. Divergence={id,order_reference:null|string,rule_code,rule_revision,status,summary,evidence_ids:string[]}; status=divergence|observation|not_evaluable.

`GET /incidents/{id}/evidence?evidence_snapshot_id=&q=&cursor=&limit=` → Page<EvidenceSummary>. EvidenceSummary={id,kind,title,version,source_system,temporal_role,excerpt}. Evidências operacionais limitadas à janela; documentos de coleção autorizada pertencem ao snapshot.

## Evidências

`GET /evidence/{id}?evidence_snapshot_id=` → Evidence. Evidence={id,kind,title,version,sha256,source_system,temporal_role,valid_from:null|string,valid_until:null|string,canonical_text,locator:{page?:number,line_start?:number,line_end?:number,char_start?:number,char_end?:number,as_of?:string},original:{media_type,byte_size,content_url}|null}. kind=document_span|source_event|delivery_attempt|order_snapshot|reconciliation_result. original.content_url relativo à API, nunca storage público. `GET /evidence/{id}/content?evidence_snapshot_id=` reautoriza antes do download. Informação revogada nunca é devolvida por cache/histórico.

## Dossiês e revisão

`POST /incidents/{id}/dossiers` `{evidence_snapshot_id,summary,claims:ClaimInput[],outcome}` →201 Dossier. origin=manual, nenhuma execução/modelo fictício. `GET /dossiers/{id}` → Dossier. Dossier={id,origin,evidence_snapshot_id,current_revision_id,approved_revision_id:null|string,revisions:RevisionSummary[],permissions:string[]}; RevisionSummary={id,number,author,created_at,review_status}.

`GET /dossiers/{id}/revisions/{revision_id}` → Revision com header ETag. Revision={id,number,base_revision_id:null|string,summary,claims:Claim[],outcome,created_by,created_at,review_status,etag}. review_status=draft|submitted|approved|changes_requested. outcome=evidence_found|conflicting_evidence|insufficient_evidence|unsupported_scope.

Claim={claim_id,kind,text,order_references:string[],evidence_links:[{evidence_id,relation}],support_status,missing_information:string[],suggested_checks:string[]}; kind=observed_fact|hypothesis; relation=supports|contradicts|context; support_status=pending_review|contested|reviewed. ClaimInput aceita claim_id opcional; servidor atribui novos IDs e valida IDs existentes da revisão-base. Não gerar alegação factual sem fonte válida; abstenção usa zero claims e summary/lacunas.

`POST /dossiers/{id}/revisions` `{base_revision_id,summary,claims:ClaimInput[],outcome}` com If-Match da base →201 Revision; 409 preserva rascunho no cliente. `POST /dossiers/{id}/submit` `{target_revision_id}` com If-Match → Revision submitted. `POST /dossiers/{id}/reviews` `{target_revision_id,claim_ids:string[],decision:'approved'|'changes_requested',reason}` com If-Match → Revision; aprovador não é autor/submissor, papel reviewer e ACL atual. Documento/revisão antigo continua imutável; estado da decisão é registro associado.

## Investigações

`POST /incidents/{id}/runs` `{evidence_snapshot_id,question}` + Idempotency-Key →202 Run, header `Location`. `GET /runs/{id}` → Run. `POST /runs/{id}/cancel` → Run. RunSummary={id,state,stage,outcome:null|string,created_at}. Run estende resumo com `{steps:[{key,status,started_at:null|string,completed_at:null|string}],cancel_requested,last_event_id,evidence_snapshot_id,dossier_id:null|string,revision_id:null|string,error:null|{code,message},started_at:null|string,completed_at:null|string,usage:{status,input_tokens:null|number,output_tokens:null|number}}`.

state=queued|running|retry_wait|succeeded|failed|cancelled. `GET /runs/{id}/events` usa SSE com `id: seq`, `event: progress|snapshot|terminal|resync_required` e data `{seq,type,payload}`. Last-Event-ID suportado; snapshot e last_event_id consistentes. Evento expirado força resync, heartbeat não representa progresso. Autorização reavaliada durante stream. Front mantém polling fallback, sem disparar outro run. Estado remoto não transmite tokens não validados.

## Importação

`POST /imports` `{collection_id,manifest:{schema_version:'1',title,source_tenant?:string,coverage:Coverage[],entries:[{entry_id,filename,kind,media_type,byte_size,sha256,metadata?:object}]}}` →201 Import. kind=events|snapshots|document|mappings. byte_size inteiro <= 10 MiB por arquivo, máximo 40 MiB / 40 entradas por pacote inicial. Nome sem /,\\, traversal ou extensão fora da allowlist; entry_id é identificador restrito. metadata de documento: title,version,source_system,valid_from,valid_until,temporal_role. Eventos e snapshot seguem data-contract/modelos da reconciliação.

`PUT /imports/{id}/files/{entry_id}` bytes Content-Type compatível →Import. `POST /imports/{id}/finalize` →202 Import. `GET /imports` e `GET /imports/{id}` → Page<Import>/Import. Import={id,collection_id,title,state,created_at,evidence_snapshot_id:null|string,entries:[{entry_id,filename,kind,byte_size,sha256,state,error:null|{code,message}}],error:null|{code,message}}. Lote all-or-nothing, receiving/sealed/processing/ready/rejected/failed/cancelled. Falha por arquivo nunca implica publicação parcial.

## Exportações

`POST /dossiers/{id}/exports` `{revision_id}` + Idempotency-Key →202 Export. `GET /exports/{id}` → Export. Export={id,state,revision_id,download_url:null|string,expires_at:null|string,error:null|{code,message}}. `GET /exports/{id}/download` entrega HTML escapado da revisão autorizada, contendo proveniência/fontes. Disponibilidade exige aprovação e acesso atual, inclusive aos derivados.

## Administração e saúde

`GET /health/live` e `GET /health/ready` não expõem segredos. Métricas endpoint interno administrativo separado de sessão de analista. Administração usa as rotas abaixo; o papel tenant_admin continua precisando de grant de coleção para ler/modificar conteúdo.

## Complementos implementados

`GET /incidents/{id}/dossiers` retorna Page com id,origin,created_at,current_revision_id,approved_revision_id. O cursor continua avançando mesmo quando uma página contém somente derivados revogados; ausência de acesso nunca vaza o conteúdo de uma revisão.

Dossier também inclui incident_id. Revision contém missing_information e suggested_checks no nível do documento, além dos campos por alegação. impact_summary é null para revisões legadas sem cálculo, ou `{observations,logical_events,orders,divergences,not_evaluable,evidence_snapshot_id,rule_revision,source:'deterministic_reconciliation'}`. Esses números são calculados no servidor e seus insumos privados participam da reautorização do derivado.

Revision.review contém submitted_by,reviewed_by,reason,claim_ids,updated_at. A decisão é associada à revisão imutável; a resposta aplica reviewed/contested às alegações cobertas pela decisão. Aprovação exige revisar todas as alegações; dossiê de insuficiência pode ter zero alegações. Nova edição perde a aprovação sem reescrever a versão antiga.

Corpos de operações comuns têm limite 512 KiB e prazo 15 s, inclusive sem Content-Length confiável; uploads de arquivo seguem o limite menor declarado no manifesto. SSE tem dois streams por usuário e 32 globais, com lease compartilhado no PostgreSQL, janela de conexão de cinco minutos e polling disponível. Fechar a conexão não cancela o job. Cancelamento continua disponível durante manutenção.

## Índice documental

`GET /evidence-snapshots/{id}/index` → `{evidence_snapshot_id,embedding_revision,indexing_enabled,disabled_reason,total_documents,indexed_documents,complete,job:null|{id,state,stage,error,attempt}}`. Capability informa configuração do perfil, não garante saúde instantânea do serviço. POST na mesma rota com Idempotency-Key admite indexação na fila, sem carregar pesos no HTTP. Snapshot/coleção e tenant são reautorizados. Mesmo snapshot já admitido retorna a mesma identidade; falha terminal aparece no job. Índice parcial não libera busca híbrida.

O perfil lexical funciona sem modelos privados. Perfil híbrido agenda indexação após importação; pesquisa sem índice completo recebe 409 `embedding_index_incomplete`. Endpoint/versão de modelos são configuração do servidor, não campos aceitos no corpo.

## Administração implementada

- `GET /admin/users`: até 100 usuários do tenant com id/nome/email/papel/estado; sem hash/senha.
- `POST /admin/collections` `{name,description}`: cria coleção e grant do administrador que a criou; não concede acesso a todo tenant.
- `PUT /admin/collections/{id}/members/{user_id}` `{granted,incident_ids}`: concede acesso aos incidentes explicitamente informados ou revoga participação; incrementa política e cancela jobs ativos afetados.
- `DELETE /admin/evidence/{id}` `{reason}` + Idempotency-Key: motivo enumerado `user_request|expired|incorrect_source|security`, tombstone imediato, registro no ledger e 202 com trabalho de remoção. Repetição idêntica retorna o mesmo pedido. Agregado derivado não é fonte removível diretamente.
- `GET /admin/deletions` e `GET /admin/deletions/{id}`: progresso e erro da remoção autorizada. Cópias por hash/coleção, dossiês e exports derivados ficam inacessíveis antes da remoção física.

Papel de admin sem grant não enumera conteúdo. O frontend principal continua voltado ao analista; essas rotas são exercitadas diretamente nos testes/contratos administrativos.

## Limites adicionais de processamento

Além do tamanho de upload, a extração acumulada de um lote não pode superar 50 mil linhas de registros, 50 mil evidências derivadas ou 8 MiB de texto UTF-8. Um lote excedente falha explicitamente com `extraction_budget_exceeded`; divida o material em pacotes menores. Isso limita o conjunto acumulado no worker, não só cada subprocesso individual.

Os stages de investigação são `reconciliation`, `planning`, `retrieval`, `generation` e `validation`; steps persistem início/fim/status. O manifesto privado registra plano permitido, configuração congelada, fontes realmente enviadas e uso; não registra raciocínio privado do modelo. Usage pode incluir estimativa/método/período além dos tokens reportados. Nenhum campo monetário inventa preço Azure.
