# Orçamento mensal de geração

`ED_AI_PERIOD_TOKEN_BUDGET` é um limite por tenant e mês civil UTC. O relógio do PostgreSQL define o período. Cada chamada guarda `provider_calls.budget_period`; um trigger impede mover uma chamada para outro mês. Reiniciar API/worker, limpar cache ou criar uma investigação não reinicia o orçamento.

A admissão considera o consumo reportado do mês atual **mais todas as reservas ainda pendentes**, inclusive de meses anteriores. Portanto, um timeout perto da virada do mês não libera cota. A reserva cobre o teto congelado de input e output antes do despacho. O consumo devolvido pelo provedor é autoritativo; se ultrapassar a reserva, o excedente é contabilizado e bloqueia admissões futuras quando necessário.

`token_budget_periods` guarda saldos por período. `provider_budget_events` registra lançamentos append-only: reserva, resultado conhecido e resultado desconhecido. A role da aplicação não pode editar ou apagar esses eventos. `tenant_policy.token_reserved/token_reported` continuam como totais históricos de compatibilidade, mas não definem sozinhos o orçamento mensal. O gauge de utilização usa `budget_position(...).committed_tokens`.

Uma resposta desconhecida mantém a reserva. Quando uma confirmação confiável chega posteriormente, `reconcile_usage` transfere a reserva para consumo no **período original**. Essa operação é idempotente, inclusive entre processos concorrentes; confirmação repetida não cobra novamente. Não há botão para zerar reservas, fallback que inventa uso zero ou liberação automática por passagem do tempo. A aplicação ainda não possui uma tela de conciliação manual com o extrato do provedor; essa operação exige reconciliação administrativa verificável.

A migração0008 importa chamadas existentes usando seu `created_at` UTC e produz lançamentos de abertura identificados como tal. Valores históricos de `tenant_policy` sem correspondência nas chamadas preservadas são mantidos no mês da migração, conservadoramente. O código não inventa uma data antiga para esses valores nem os descarta. O [probe de migração](../evals/reports/monthly-budget-migration.json) verificou um saldo de chamada desconhecida anterior e valores sem atribuição preservados.

O rollout da0008 requer workers gerativos parados durante migração e atualização: o código antigo não preenche `budget_period`. Atualize banco, API e workers de forma coordenada. A migração foi verificada no PostgreSQL descartável de testes; o comando de deploy deve aplicar o mesmo procedimento no ambiente pretendido.

Testes em PostgreSQL real cobrem virada de mês, reserva desconhecida carregada, confirmação tardia, reinício de conexões, reconciliação concorrente, isolamento RLS, ledger sem permissão de alteração e imutabilidade do período. A configuração atual suporta somente `calendar_month_utc`; períodos móveis e faturamento monetário por tabela de preços não estão implementados.
