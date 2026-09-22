# Auditoria do frontend para publicação

Data: 21/09/2026. Escopo: bancada, importação, revisão, acessibilidade dos formulários e documentação do frontend. Consulte a [revisão da arquitetura](frontend-review.md) e o [guia de execução](../frontend/README.md).

## Problemas corrigidos

- **Coleções após o limite inicial:** a API e os dois formulários só alcançavam as primeiras cem coleções. A API agora fornece cursor, e incidente/importação compartilham um seletor com “Carregar mais coleções”, erro recuperável e estado vazio.
- **Alterações durante gravação:** era possível continuar editando campos enquanto o servidor recebia a versão anterior. Incidente, investigação, dossiê e decisão bloqueiam seus controles durante a requisição para não descartar alterações silenciosamente.
- **Limites divergentes:** a justificativa aceitava quatro mil caracteres onde a API aceita três mil. Alegações também careciam de validação local dos limites de fontes, pedidos e notas. Os limites foram alinhados e recebem mensagens em português. Um resultado com evidências exige alegações citadas antes do envio.
- **Trabalho de revisão não salvo:** fechar a decisão descartava a justificativa sem aviso. A interface agora confirma o descarte e protege recarregamentos quando há alterações.
- **Erros dos formulários:** campos de criação, resumo, resultado, alegação e pergunta de investigação agora expõem estado inválido e descrição associada ao erro; a navegação principal informa a página atual.
- **Mensagem de IA indisponível:** detalhes de configuração do servidor foram substituídos por uma orientação ao investigador: continuar a investigação e editar o dossiê manualmente.
- **Documentação que dependia de arquivos ignorados:** a revisão antiga apontava relatórios e imagens locais ausentes em um clone novo. A revisão atual aponta código, comandos reproduzíveis e imagens selecionadas para versionamento.

## Evidência desta revisão

`npm run typecheck`, `npm run lint`, `npm run format:check` e `npm run test` passaram após as mudanças. Resultado dos unitários: **61 testes em 10 arquivos**, incluindo oito regressões novas para limites de alegações e resultado sem fontes.

A regressão `publication-regressions.spec.ts` foi adicionada para seleção de coleções após cem itens, descrição acessível de erros e gravação de incidente/dossiê com resposta atrasada. A jornada de revisão existente também verifica o máximo de três mil caracteres e a preservação da justificativa após recusar o descarte.

A rodada completa de Playwright começou em **21/09/2026 às 22:11:12 UTC** contra as imagens de produção no projeto Compose isolado: **11 passaram em 38,6 s**, **1 ignorado explicitamente**, zero falhas e zero retries. O teste opcional ignorado exige IDs de uma geração Azure existente; o laboratório desativa o provedor pago. A identificação das imagens, o resultado de cada caso e as contagens estão no [resumo estruturado](evidence/publication-frontend.json).

Foram exercitados login e troca de organização, divergências e fontes, revalidação da sessão e revogação controlada, dossiê manual, conflito real entre revisões, segundo revisor, exportação, importação e renderização PDF reais, teclado, regras axe e larguras 320/768/1440 px. A nova regressão de paginação e gravação lenta também passou. O teste PDF confirmou pixels renderizados e o SHA-256 do original.

A inspeção adicional pelo navegador in-app usou a conta sintética Bruno: fila, abertura do incidente, título e conteúdo da fonte, foco no leitor e apresentação da bancada. Não foram criadas novas investigações de IA.

Depois da última alteração, restrita ao texto de IA indisponível na API, a mensagem foi conferida novamente pelo navegador in-app. A jornada visual foi repetida às **22:17:22 UTC**: **1 passou em 7,3 s**, sem skip, falha ou retry, usando a mesma imagem frontend e a API atualizada. O resumo estruturado preserva as identidades de ambas as execuções; a rodada completa não é atribuída à imagem posterior.

## Imagens versionadas

As capturas usam dados sintéticos da execução real. O leitor móvel mantém o nome do incidente, a navegação e o texto original; a tabela da bancada usa rolagem própria em telas estreitas.

![Bancada de investigação com evidência aberta a 1440 px](images/workspace-desktop.png)

![Leitor de fonte a 320 px](images/source-mobile.png)

Os relatórios brutos e traces temporários permanecem ignorados pelo Git. O resumo acima contém somente campos de teste selecionados, sem caminhos pessoais, cookies ou credenciais.

## Revisão documental e de coerência em 22/09/2026

Esta revisão leu os componentes, jornadas e o resumo acima e inspecionou as duas imagens versionadas. O desenho foi preservado; não houve alteração de UI, nova captura ou execução de navegador. As imagens mostram o estado registrado em 21/09, não uma nova medição.

| Tarefa do usuário | Coerência observada e prova existente |
| --- | --- |
| Conferir divergência sem perder o recorte | A bancada mostra período, snapshot e cobertura antes das abas; a fonte abre ao lado da divergência em desktop. O [workspace](../frontend/src/features/incidents/incident-workspace.tsx) distingue contagens/cobertura do snapshot ativo dos registros de um snapshot anterior, com aviso explícito. |
| Ler uma fonte no celular e voltar | A captura a 320 px mantém incidente, título e botão de retorno. A [jornada visual](../frontend/e2e/visual.spec.ts) verifica ausência de overflow global em 320/768/1440 e retorno do foco ao acionador. A imagem sozinha não comprova o foco. |
| Esperar uma leitura ou lidar com acesso negado | O [leitor](../frontend/src/features/evidence/evidence-reader.tsx) oculta dados durante revalidação e erro. A [jornada de fonte protegida](../frontend/e2e/protected-source.spec.ts) identifica a recusa controlada de transporte; a ACL real tem testes backend separados. |
| Editar, discordar e aprovar | A [jornada manual](../frontend/e2e/investigation.spec.ts) cobre conflito real 409, texto preservado, segundo revisor e exportação. Aprovar abstenção não muda a conclusão para causa comprovada. |
| Acompanhar uma tentativa sem confundir um resultado anterior | O [painel de investigação](../frontend/src/features/incidents/run-panel.tsx) mostra identidade, horários, etapa, uso conhecido/desconhecido e aviso de que aprovação anterior não prova sucesso atual. Os [estados controlados](../frontend/e2e/controlled-states.spec.ts) não são uma nova chamada Azure. |
| Usar teclado e formulários | [Acessibilidade](../frontend/e2e/accessibility.spec.ts) cobre axe e ajuste de largura pelo teclado; [regressões de publicação](../frontend/e2e/publication-regressions.spec.ts) cobrem erros associados e formulários bloqueados durante gravação. Não é certificação WCAG nem ensaio com leitor de tela. |

Não se encontrou inconsistência que justificasse mudar o desenho nesta leitura. Isso é uma revisão estática limitada aos estados presentes nas fontes e às duas capturas, sem novo teste de zoom nativo, leitor de tela ou uso por analistas. O [guia de problemas e decisões](problem-solution.md) explica os casos e limites operacionais associados. A única verificação executada nesta rodada é o verificador offline de links publicáveis `scripts/check_repository_docs.py`, além da conferência de whitespace do diff.

## Nova jornada manual de pagamento em 22/09/2026

Depois da leitura documental acima, executei a [jornada de pagamento](../frontend/e2e/payment-story.spec.ts) contra o aplicativo real em um projeto Compose próprio. Não alterei componentes, estilos ou respostas para preparar imagens. A rodada final teve **1 pass, zero skips, falhas e retries**; o [registro de navegador](evidence/editorial-payment-20260922/browser-review.json) conserva a versão do teste, os hashes das capturas e a separação da primeira tentativa. As contas são sintéticas e ambas foram operadas pela automação.

O [roteiro com imagens](demo.md) acompanha uma nova investigação sobre a mesma janela e snapshot de `demo-aurora-09`: pagamento às 12:00:30 UTC, estado pendente às 12:10 UTC, duas divergências, elaboração manual, decisão por Bruno e HTML exportado. A abertura/fechamento de fonte verifica o retorno de foco ao acionador. A captura de 390 px espera a reautorização após redimensionar. Os recortes preservam os originais completos; não são um novo desenho da interface.

Os **61 testes frontend em 10 arquivos**, TypeScript e lint/formatação do novo teste passaram. As verificações desta rodada não repetem toda a matriz anterior de acessibilidade, zoom e larguras. A negativa recebida por Ana comprova a falta do papel de revisora; a proibição de autor com esse papel aprovar a própria revisão é coberta separadamente pelo [teste de integração](../backend/tests/integration/test_manual_workflow.py), executado nesta rodada. Aprovação, contagem de divergências e correção operacional continuam sendo fatos distintos.
