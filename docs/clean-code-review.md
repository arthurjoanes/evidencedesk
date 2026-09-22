# Revisão de clean code

A avaliação atual está na [revisão de arquitetura](architecture-review-publication.md) e na [revisão do frontend](publication-frontend.md). As observações abaixo preservam os exercícios de manutenção da implementação original.

A revisão acompanha responsabilidades e garantias: localizar uma regra, alterar seu comportamento e verificar as consequências. Os resultados da versão atual estão na [verificação para publicação](publication.md).

| Dimensão        | Avaliação             | Arquivo/linha de entrada                                                                          | Consequência e ação                                                                                                                                                          |
| --------------- | --------------------- | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Nomes e domínio | Forte                 | `backend/src/evidencedesk/reconciliation/contracts.py:147`                                        | EventObservation, TimelineRow e Divergence preservam significados diferentes. Usar os mesmos termos em API/docs.                                                             |
| Coesão          | Forte                 | `backend/src/evidencedesk/reconciliation/rules.py:42`                                             | Regra pura recebe dados autorizados; não conhece HTTP, Azure ou credenciais. Oráculos pequenos exercitam tempo/cobertura.                                                    |
| Pastas          | Forte                 | `backend/src/evidencedesk/investigations/tools.py:97`                                             | Capacidades reconhecíveis: identidade, ingestão, incidentes, investigação, revisão, retenção. Evitar novas camadas para encaminhar argumentos.                               |
| Complexidade    | Adequada com ressalva | `backend/src/evidencedesk/jobs/service.py:121`                                                    | Locks/fencing/uso externo são complexidade necessária. Expiração agora fecha steps/eventos e impede repetir chamada já reportada; manter testes de crash junto de mudanças.  |
| Acoplamento     | Adequada com ressalva | `backend/src/evidencedesk/reviews/service.py:14`                                                  | Autorizar derivado exige atravessar fontes/revisões; imports locais evitam ciclo, mas a dependência merece acompanhamento. Não criar repository genérico para escondê-la.    |
| Contratos       | Adequada com ressalva | `backend/src/evidencedesk/model_runtime/contracts.py:14`                                          | Pydantic/Zod nas fronteiras e protocolo pequeno de modelos. Linhas SQL ainda circulam como `dict`; tipar projeções estáveis é evolução útil, sem casts para silenciar erros. |
| Erros           | Forte                 | `backend/src/evidencedesk/errors.py:1`                                                            | Code/status/message/retryable separam diagnóstico e UI. Timeout desconhecido não vira zero; pool exaurido vira503. Não engolir exceção nem retornar lista vazia.             |
| Duplicação      | Adequada com ressalva | `backend/src/evidencedesk/retention/cleanup.py:88`                                                | CAS unifica liberação por purge/expiração/replay. Há SQL repetido de autorização por fronteira; remover somente se mantiver o contexto/lock visível.                         |
| Testabilidade   | Forte                 | `backend/tests/integration/test_worker_failures.py:1`                                             | Role PostgreSQL real, dois processos e transporte simulado apenas onde indicado. Fixtures cuidam do estado global do provedor e usam namespace descartável.                  |
| Frontend        | Forte                 | `frontend/src/lib/session.tsx:28`, `frontend/src/features/evidence/reconciliation-summary.tsx:13` | Cache por sessão/tenant e componentes pelo trabalho do analista; apresentação não recalcula conciliação. E2E verifica foco, erro e conflito.                                 |
| Operação        | Adequada com ressalva | `scripts/ops.py:1`, `scripts/backup.py:1`                                                         | Comandos propagam falha e não removem volumes globais. Cache de listagem resolveu custo medido; orçamento do host compartilhado ainda limita ensaios.                        |
| Documentação    | Adequada com ressalva | `docs/verification.md:1`                                                                          | Matriz distingue real, fixture e pendente. Manter relatos negativos e comandos; um YAML ou teste unitário de SDK não comprova hospedagem.                                    |

Fontes desta seção, conferidas em **22/09/2026**: [test_maintenance_examples.py](../backend/tests/unit/test_maintenance_examples.py) · [reconciliation-content.ts](../frontend/src/features/evidence/reconciliation-content.ts) · [evidence-reader.tsx](../frontend/src/features/evidence/evidence-reader.tsx).

## Exercício 1 — novo evento observado

Incluído o caso `shipment.delivery_attempted` em [test_maintenance_examples.py](../backend/tests/unit/test_maintenance_examples.py). Ele atravessa o contrato de evento, mapeamento explícito, conciliação e geração da evidência canônica. A timeline preserva tipo/pedido; uma observação e um evento lógico não criam uma divergência inventada.

Arquivos alterados para o exercício: somente esse teste. O contrato já permite tipos de evento extensíveis; `evidence_records` apresenta `source_event` e título de domínio. Nenhuma mudança no leitor, parser ou auth foi necessária. O teste passou com `python -m pytest backend/tests/unit/test_maintenance_examples.py -q`. Acrescentar uma regra de negócio específica para o evento seria outra alteração, com outro oráculo; este exercício não finge implementá-la.

Fontes desta seção, conferidas em **22/09/2026**: [test_maintenance_examples.py](../backend/tests/unit/test_maintenance_examples.py).

## Exercício 2 — apresentação de conciliação

O agregado antes aparecia como texto JSON. Foram acrescentados [reconciliation-content.ts](../frontend/src/features/evidence/reconciliation-content.ts), [reconciliation-summary.tsx](../frontend/src/features/evidence/reconciliation-summary.tsx) e a escolha de modo no [EvidenceReader](../frontend/src/features/evidence/evidence-reader.tsx). O formato original, números, escapes e hash continuam preservados. Ausência de campo não é zero.

A regra de conciliação e o conteúdo persistido foram preservados. Testes unitários cobrem contradições e preservação lexical; a rodada histórica de navegador abriu o resultado Azure existente e verificou leitura móvel/axe. A mudança demonstrou separação de apresentação e domínio. As capturas atuais estão na [revisão do frontend](frontend-review.md).

Fontes desta seção, conferidas em **22/09/2026**: [reconciliation-content.ts](../frontend/src/features/evidence/reconciliation-content.ts) · [reconciliation-summary.tsx](../frontend/src/features/evidence/reconciliation-summary.tsx) · [evidence-reader.tsx](../frontend/src/features/evidence/evidence-reader.tsx).

## Achados corrigidos na revisão

- Listagem refazia a conciliação para cada item e saturava o pool: projeção pequena com cache limitado, autorização atual e invalidação por política, sem cache de dossiês privados.
- Repetição de upload poderia acumular objetos/reservas: escrita imutável, token, estado selado e ownership/CAS de quota.
- Worker podia expirar depois de contabilizar a chamada e chamar o provedor novamente: aquisição agora recusa repetição após qualquer dispatch efetivo, inclusive uso reportado.
- Usage final substituía metadados de estimativa: publicação faz merge com uso já persistido.
- Último run/dossiê podia expor ID de derivado inacessível: seleção reautoriza candidatos e omite os indisponíveis.
- Reabrir fonte poderia reapresentar cache antes da permissão atual: o frontend descarta consultas protegidas sem observadores e oculta conteúdo durante a reautorização. O E2E segura a resposta para verificar justamente esse intervalo.
- Limites por arquivo não impediam expansão cumulativa de quarenta documentos: o worker passa a aplicar orçamento por lote antes de acumular extrações/evidências.

Os módulos de concorrência e exclusão precisam continuar sendo revisados por suas invariantes. A ordem dos locks e as condições de publicação devem permanecer visíveis ao alterar esses módulos.

Fontes desta seção, conferidas em **22/09/2026**: [test_maintenance_examples.py](../backend/tests/unit/test_maintenance_examples.py) · [reconciliation-content.ts](../frontend/src/features/evidence/reconciliation-content.ts) · [evidence-reader.tsx](../frontend/src/features/evidence/evidence-reader.tsx).
