# Problemas, exemplos e decisões

Desenvolvi o EvidenceDesk para investigar pedidos cujo pagamento, estoque e estado operacional não concordam. Reuni fontes autorizadas, regras de conciliação e uma conclusão revisável. Os dados de demonstração são sintéticos; não houve estudo com analistas que demonstre redução de tempo ou benefício comercial. As razões abaixo explicam efeitos e compromissos da implementação atual, sem atribuir uma motivação histórica não registrada.

Fontes desta seção, conferidas em **22/09/2026**: [rules.py](../backend/src/evidencedesk/reconciliation/rules.py) · [reviews/service.py](../backend/src/evidencedesk/reviews/service.py) · [budget.py](../backend/src/evidencedesk/investigations/budget.py).

## Pagamento confirmado e pedido pendente

Abra `demo-aurora-09`, **Divergências**, e confira as duas fontes da comparação: evento de pagamento e snapshot do sistema de pedidos. A regra considera o instante do fato e o `as_of` do snapshot, além do mapeamento do pedido e da incerteza dos relógios. A data de importação não prova a ordem dos acontecimentos.

No [gerador da demonstração](../datasets/generate.py), `incident_records` define `PED-009-000` com pagamento às **12:00:30 UTC de 09/07/2026** e snapshot `pending_payment` às **12:10:00 UTC**. A diferença é de 570 segundos. Com prazo de 300 segundos, a confirmação seria esperada até **12:05:30 UTC**; a coleta de pedidos está declarada completa até 12:30:00 UTC e não contém essa transição. Os resultados esperados são `payment_snapshot_mismatch` e `transition_not_observed`, ambos sobre o mesmo pedido. Os outros 221 pedidos normais explicam o total de 222 no recorte.

Um exemplo pequeno está na fixture de [conciliação](../backend/tests/unit/test_reconciliation.py): pagamento aos 10 segundos e snapshot pendente aos 400 produzem `payment_snapshot_mismatch`; mover o snapshot para 5 segundos elimina essa comparação. Relógio desconhecido ou instantes próximos demais para sua precisão produzem uma avaliação inconclusiva. Ausência de transição exige cobertura suficiente até o prazo; o sistema não transforma falta de coleta em prova de falha.

Separei cálculo e redação nas [regras puras](../backend/src/evidencedesk/reconciliation/rules.py), chamadas por `load_reconciliation` no [serviço de incidentes](../backend/src/evidencedesk/incidents/service.py). Isso torna o resultado reproduzível, ao custo de exigir regras e contratos explícitos para cada integração. Uma consulta SQL específica poderia bastar em um caso isolado; aqui o contrato também preserva quais fontes, snapshot e revisão de regra sustentam cada resultado. A divergência indica o que merece investigação; não identifica sozinha a causa nem corrige o pedido. [Contrato temporal e de cobertura](data-contract.md).

Fontes desta seção, conferidas em **22/09/2026**: [generate.py](../datasets/generate.py) · [test_reconciliation.py](../backend/tests/unit/test_reconciliation.py) · [rules.py](../backend/src/evidencedesk/reconciliation/rules.py).

## Reentrega não comprova cobrança duplicada

A [documentação de webhooks da Stripe](https://docs.stripe.com/webhooks#event-delivery-behaviors) descreve reentregas e ausência de garantia de ordem. Este projeto reproduz essas condições com arquivos sintéticos e separa identidade lógica de observação; não recebe webhooks Stripe nem implementa cobrança. A fonte documenta um comportamento de plataforma, não mede a frequência do problema ou o benefício deste laboratório.

Receber novamente o mesmo ID lógico, com o mesmo conteúdo, gera outra observação. Na mesma fixture, duas observações resultam em **um evento lógico e um pedido**, com `delivery_count=2`. A UI apresenta a reentrega como observação. Se o mesmo ID traz conteúdo conflitante, a regra marca o conflito como não avaliável e não escolhe arbitrariamente uma das versões para comparar o pagamento.

O motivo é operacional: entrega de mensagem e operação financeira têm identidades diferentes. Investigar duas cobranças requer suas evidências; contar linhas de log não basta. Os testes `test_redelivery_does_not_duplicate_logical_event_or_orders` e `test_same_identity_with_changed_domain_content_is_not_consolidated` fixam essa distinção.

Fontes desta seção, conferidas em **22/09/2026**: [rules.py](../backend/src/evidencedesk/reconciliation/rules.py) · [reviews/service.py](../backend/src/evidencedesk/reviews/service.py) · [budget.py](../backend/src/evidencedesk/investigations/budget.py).

## Uma fonte disponível ontem pode estar proibida hoje

O snapshot conserva as fontes usadas, mas não conserva para sempre a permissão de quem o abriu. A autorização combina organização, coleção e incidente; uma conciliação derivada também exige acesso ao incidente de origem. A API revalida cada leitura, ferramenta e exportação. Na interface, reabrir uma fonte espera a autorização atual e oculta o texto em cache durante a verificação ou após recusa.

[Identidade](../backend/src/evidencedesk/identity/service.py), [escopo das evidências](../backend/tests/integration/test_evidence_scope.py) e [revogação real](../backend/tests/integration/test_administration.py) demonstram a regra no servidor. A [jornada do leitor](../frontend/e2e/protected-source.spec.ts) usa uma primeira leitura real e uma recusa de transporte controlada; ela verifica a proteção visual, sem se apresentar como uma nova revogação real no banco.

RLS oferece uma segunda fronteira por organização, com role sem privilégios de bypass; não substitui as permissões do domínio. As propriedades e exceções de RLS estão na [documentação do PostgreSQL](https://www.postgresql.org/docs/17/ddl-rowsecurity.html), e a revalidação por acesso segue a orientação da [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html). O custo é aplicar a política também aos resultados derivados e reautorizar a leitura, em vez de confiar apenas no cache.

Fontes desta seção, conferidas em **22/09/2026**: [identity/service.py](../backend/src/evidencedesk/identity/service.py) · [test_evidence_scope.py](../backend/tests/integration/test_evidence_scope.py) · [test_administration.py](../backend/tests/integration/test_administration.py).

## Revisões concorrentes e aprovação independente

Se Ana e outro analista editam a mesma base, a primeira gravação cria uma revisão. A segunda recebe conflito 409; o editor preserva seu texto para comparação e nova decisão. O cabeçalho HTTP `If-Match` informa a versão esperada: junto da revisão-base, impede sobrescrita silenciosa. Editar novamente cria outra revisão, que não herda a aprovação anterior.

Depois da submissão, nem o autor nem quem submeteu podem aprovar. O revisor confere a versão e as alegações exatas; a exportação exige revisão aprovada e permissão atual. É possível aprovar uma abstenção bem fundamentada: isso registra a revisão humana, não uma causa confirmada. [Serviço de revisão](../backend/src/evidencedesk/reviews/service.py), [integração de conflito/aprovação/exportação](../backend/tests/integration/test_manual_workflow.py) e [jornada manual](../frontend/e2e/investigation.spec.ts).

Implementei esse vínculo na revisão: `validate_claims` revalida cada fonte e retira a aprovação semântica ao editar; `assert_base_revision` exige base e `If-Match` atuais; `review_revision` impede que autor ou submissor aprovem e exige todas as alegações da versão. Uma simples edição do texto atual seria menor, mas perderia a comparação com aquilo que outra pessoa conferiu. **“Resolvido” é o estado da investigação após aprovação do dossiê**, não uma confirmação de que o pedido ou pagamento foi corrigido. O serviço não executa essa remediação.

Essa escolha preserva a responsabilidade de cada decisão, mas exige trabalho de comparação. Revisão imutável significa que edições não reescrevem a versão anterior; uma exclusão administrativa de fontes continua tendo efeitos auditados sobre sua disponibilidade e seus derivados.

Fontes desta seção, conferidas em **22/09/2026**: [reviews/service.py](../backend/src/evidencedesk/reviews/service.py) · [test_manual_workflow.py](../backend/tests/integration/test_manual_workflow.py) · [investigation.spec.ts](../frontend/e2e/investigation.spec.ts).

## A tentativa de IA pode terminar com resultado incerto

Uma queda depois do envio ao provedor pode perder a resposta antes de gravá-la. Repetir automaticamente poderia cobrar duas chamadas. A tentativa expirada não é repetida depois do despacho, mesmo quando algum uso já foi reportado. A reserva desconhecida continua comprometendo orçamento; uma confirmação tardia concilia o consumo no mês UTC original, de forma idempotente. [Falhas do worker](../backend/tests/integration/test_worker_failures.py), [contabilidade mensal](../backend/tests/integration/test_monthly_budget.py) e [orçamento](token-budget.md).

O painel distingue tentativa, etapa, erro e uso; uma revisão aprovada anterior não representa sucesso da tentativa atual. Reabrir um resultado persistido não gera novamente. Tokens conhecidos, reserva e uso desconhecido são estados diferentes; o produto não converte esses números em fatura monetária. A reserva conservadora pode bloquear novas admissões até uma conciliação administrativa verificável.

A [prova Azure histórica](verification.md) registra uma geração real, com 1.166 tokens de entrada e 784 de saída, e reabertura após reinício. Isso não é uma avaliação de qualidade semântica. Schema e citações válidos não demonstram que cada frase é sustentada; o rascunho continua sujeito à revisão humana. Nenhuma nova chamada paga foi feita nesta revisão documental.

Fontes desta seção, conferidas em **22/09/2026**: [test_worker_failures.py](../backend/tests/integration/test_worker_failures.py) · [test_monthly_budget.py](../backend/tests/integration/test_monthly_budget.py).

## Retenção sem ressuscitar fontes excluídas

Temporários e exportações vencidas podem ser removidos sem apagar por idade os dossiês publicados. No perfil local, a exportação vale 24 horas; a revisão continua no banco. A rotina só libera quota após confirmar a limpeza, respeitando referências e produtores ativos. Falhas físicas ficam registradas para nova tentativa, sem descontar os mesmos bytes duas vezes.

Uma exclusão posterior ao backup precisa continuar valendo depois da restauração. Por isso o procedimento reaplica o ledger de exclusões. O [ensaio preservado](evidence/erasure-restore-20260921.json) verifica fonte, original e dossiê indisponíveis após restore, com o objeto ausente. Os [testes de retenção](../backend/tests/integration/test_retention.py) e o [runbook](runbooks/retention.md) detalham pisos, lotes e recuperação. A rotina local não inicia um agendador nem comprova retenção entre hosts ou em Blob.

Fontes desta seção, conferidas em **22/09/2026**: [erasure-restore-20260921.json](evidence/erasure-restore-20260921.json) · [test_retention.py](../backend/tests/integration/test_retention.py).

## Como ler as provas

Os exemplos acima apontam implementações e testes existentes. As execuções, datas e limites estão na [verificação para publicação](publication.md); o [roteiro de demonstração](demo.md) permite explorar o fluxo manual. Uma revisão documental anterior, também em 22/09/2026, conferiu fontes e capturas versionadas sem nova execução. O [mapeamento da interface](publication-frontend.md) conserva esse escopo histórico; a jornada de pagamento tem comando e evidência próprios. Hospedagem completa no Azure, alta disponibilidade e qualidade humana suficiente continuam fora do resultado demonstrado.

Fontes desta seção, conferidas em **22/09/2026**: [rules.py](../backend/src/evidencedesk/reconciliation/rules.py) · [reviews/service.py](../backend/src/evidencedesk/reviews/service.py) · [budget.py](../backend/src/evidencedesk/investigations/budget.py).

## Recuperação verificável também pela interface

O [ensaio de reabertura](restore-read-story.md) complementa o restore fechado: aplicou o ledger de exclusão atual, conferiu os objetos e só então abriu outro destino local. O navegador autenticado leu o incidente sobrevivente; fonte, original e dossiê excluídos continuaram retornando 404, com ausência física conferida separadamente. A origem permaneceu em manutenção durante a janela de leitura, evitando tratar um ledger antigo como autorização para reabrir. São 108 referências remanescentes desta execução sintética; os restores históricos têm outros conjuntos e durações.

A mesma página apresenta rastreabilidade da revisão e conflito de edição como casos anteriores ao backup, sem confundir esses cenários. O [pacote de avaliação semântica](../evals/human-review/README.md) trata outra questão: se a fonte realmente sustenta a frase. Está preparado, sem participantes ou resultados novos.

Fontes desta seção, conferidas em **22/09/2026**: [rules.py](../backend/src/evidencedesk/reconciliation/rules.py) · [reviews/service.py](../backend/src/evidencedesk/reviews/service.py) · [budget.py](../backend/src/evidencedesk/investigations/budget.py).
