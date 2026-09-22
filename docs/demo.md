# Demonstração de cinco minutos

Pré-condição: seed carregado, API/worker/Next healthy. Use apenas contas fictícias. O roteiro não exige nova chamada paga: o fluxo manual funciona sem gerador; na máquina em que o smoke foi executado, o resultado Azure existente pode ser reaberto.

O caso de pagamento pendente é `demo-aurora-09`, também usado nas [capturas versionadas](publication-frontend.md). Na bancada, **Pedidos/Divergências no snapshot ativo** e a cobertura geral continuam descrevendo o snapshot ativo. Se escolher um snapshot anterior, o aviso explica que os registros abaixo seguem o recorte selecionado. Confira essa diferença antes de comparar contagens. O [guia de casos](problem-solution.md) explica os resultados esperados e aponta os testes, sem exigir que a apresentação provoque revogação, falha de worker ou exclusão de dados.

| Tempo | Ação | O que observar |
| --- | --- | --- |
| 0:00–0:40 | Entrar como Ana, abrir “Pagamento confirmado e pedido pendente” | Tenant, janela, snapshot, cobertura e divergências; não confundir data de ingestão com ocorrência. |
| 0:40–1:30 | Selecionar um pedido e abrir fonte do pagamento e snapshot | O evento confirma pagamento; snapshot posterior permanece incompatível. Clique na regra e confira localização da fonte. |
| 1:30–2:20 | Ir à timeline e conferir cobertura | Ausência de transição significa não observada no recorte. Uma reentrega não prova cobrança duplicada. |
| 2:20–3:15 | Criar/abrir dossiê manual, registrar hipótese citada e lacuna | Uma alegação pode ser contestada; fatos, hipótese, contexto e contraevidência não são estados equivalentes. Edite e veja nova revisão. |
| 3:15–4:10 | Submeter; entrar como Bruno e comparar a revisão exata | O autor não aprova a própria submissão; aprovação aponta IDs de alegações. Exporte somente depois de aprovar. |
| 4:10–5:00 | Mostrar revisão antiga e relatório de falha/recuperação | Conflito409 preserva rascunho; queda após dispatch não dispara nova chamada; restore verificou objetos e ledger. Não provocar nova falha destrutiva na demo. |

Resultado real de IA disponível nesta execução: run `2605b0dcf3fd4045a345a51fd2f80bdf`, incidente `demo-aurora-01`, dossiê `35de4e41bc4f4a1c863ecbf665bf1505`. Abra pelo incidente de reentrega. Há três alegações em rascunho e fontes do agregado determinístico. Outro checkout só possui esse resultado se restaurar os dados correspondentes; o seed não falsifica uma chamada Azure.

Para mostrar revogação, use o ensaio isolado em `test_administration.py`; não revogue a coleção principal durante apresentação sem preparar a recuperação. Captura de erro controlado do frontend é fixture de transporte, identificada como tal, e não falha real do Azure.

Se um dado não estiver disponível, aponte a lacuna. A demonstração deve permitir conferir e discordar, não apenas admirar texto gerado.

## Provas para acompanhar a apresentação

A [sequência com capturas de 22/09](restore-read-story.md) mostra uma revisão aprovada com sua fonte, um conflito real 409 preservando rascunho e a leitura de incidente após restauração. Revisão/conflito aconteceram na origem antes do backup; restauração/exclusão têm run e destino próprios. A aprovação usou duas contas por automação, sem revisor humano nem geração por modelo. As imagens permitem conferir o mecanismo, enquanto o [pacote semântico](../evals/human-review/README.md) prepara a avaliação de qualidade ainda pendente.
