# Revisão de UI/UX de 12/10/2026

O EvidenceDesk atende quem precisa confrontar uma alegação com registros de um snapshot e decidir se a conclusão pode seguir para revisão. A bancada da aplicação usa a API e as permissões atuais. O workbench de avaliação usa arquivos locais, duas anotações independentes e adjudicação pela CLI. A aprovação de um dossiê da aplicação não aprova um sistema de IA no laboratório.

## Jornadas e critérios

| Jornada               | Estado inicial e ação                                                | Resultado esperado                                                                | Falha a conferir                                                                                           |
| --------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Localizar o caso      | Conta sintética autorizada; buscar incidente e abrir o recorte       | Filtro, organização, snapshot e pedido continuam identificáveis ao voltar         | Nenhum resultado oferece um próximo passo; erro de transporte permite tentar novamente                     |
| Conferir uma citação  | Revisão autorizada; abrir a fonte de uma alegação                    | Alegação, relação e fonte aparecem juntas; voltar devolve o foco à citação        | Recusa, sessão ou associação inválida escondem conteúdo protegido                                          |
| Preparar o dossiê     | Analista; escrever alegação e vincular fontes do snapshot            | Salvar cria revisão; submeter a deixa pendente                                    | Validação aponta campos; conflito conserva o rascunho; autor não aprova                                    |
| Revisar a versão      | Outra conta; escolher decisão, conferir alegações e justificar       | Aprovação exige escolha explícita e confirmação de cada alegação da versão        | Acesso em revalidação oculta conteúdo; 409 conserva decisão e justificativa                                |
| Julgar no laboratório | Bundle cego local; selecionar alegação, ler fonte, julgar e exportar | Fonte precede decisão no móvel; arquivo distingue rascunho e submissão para a CLI | Motivo ou referência incompleta recebe erro junto ao campo; arquivo inválido não substitui material válido |

## Diagnóstico

As capturas usam dados fictícios. O diagnóstico registra comportamento observado em código e navegador; não deriva de entrevistas, pesquisa com usuários ou medição de produtividade.

| Evidência anterior                                                                                               | Quem é afetado   | Severidade e mudança                                                              | Aceitação                                                                            |
| ---------------------------------------------------------------------------------------------------------------- | ---------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `review-decision.tsx` iniciava com `approved`; diálogo mostrava quantidade, sem texto das alegações              | Revisor          | P1 de fluxo: retirar decisão automática e mostrar as alegações antes da aprovação | Justificativa sozinha não aprova; cada alegação real precisa de confirmação          |
| Leitor móvel de citação conservava o incidente, mas perdia a alegação de origem                                  | Analista/revisor | P1 de contexto: incluir associação conferida com a revisão selecionada            | Contexto coincide com claim, fonte e snapshot; IDs estrangeiros não criam associação |
| Busca de fontes usava estado do componente e desaparecia ao trocar de aba                                        | Analista         | P2 de navegação: guardar busca aplicada na URL e oferecer limpeza                 | Abas, voltar e recarregar preservam o filtro; limpar restaura o recorte              |
| Workbench colocava fonte depois dos campos de julgamento em 320–1024 px; cabeçalho ocupava a primeira tela móvel | Avaliador local  | P1 de leitura: caso em foco e ordem alegação → fonte → decisão                    | Fonte legível antes de selecionar o julgamento nas cinco larguras                    |
| Erros do workbench apareciam só no aviso global; achados críticos exigiam seleção múltipla com Ctrl              | Avaliador local  | P2 de operação: erro junto ao campo, foco e checkboxes                            | Teclado e toque operam cada achado; exportação incompleta indica como corrigir       |

A decisão preselecionada não demonstrava aprovação sem autorização: os controles do backend continuavam ativos. O tamanho pequeno das citações motivou melhoria de leitura e toque; a baseline não apresentou falha automatizada de contraste nem overflow global.

## Direção e alternativas

O teclado da baseline também confirmou uma falha de retorno de foco ao fechar o diálogo de revisão nas cinco larguras, mesmo esperando até cinco segundos. O retorno da fonte passou nas dez verificações. A correção do diálogo é P1 de navegação: fechar com Escape deve retornar ao iniciador visível da mesma sessão. Fechar uma fonte aberta por link direto usa uma seleção ou região de conteúdo como destino, pois não há iniciador anterior.

Na aplicação, ficam IBM Plex Sans para leitura e IBM Plex Mono para identificadores; o workbench conserva Segoe UI/Cambria. A [paleta de marca](brand.md) usa azul petróleo `#14566B`, azul profundo `#0B3448`, névoa `#EAF3F6`, papel `#F5F8FA`, grafite `#202B36` e ardósia `#536573` nas duas interfaces. Estados de erro, sucesso e aviso conservam cores e rótulos próprios. Espaços acompanham os grupos da tarefa; detalhes técnicos ficam disponíveis sem dominar a decisão.

| Tela           | Composição comparada                                                                                   | Escolha                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| Investigação A | Cabeçalho de recorte → abas atuais → dossiê e leitor; alegação no leitor; decisão explícita no diálogo | Selecionada. Preserva a investigação e aproxima a citação de sua alegação          |
| Investigação B | Lista de alegações fixa à esquerda e fonte ampla à direita, com decisão no rodapé                      | Descartada. Exigiria nova navegação e reduziria o espaço da conciliação e timeline |
| Workbench A    | Fila, julgamento e fonte em três colunas permanentes                                                   | Descartada. Comprime o confronto em larguras intermediárias                        |
| Workbench B    | Caso em foco, fila recolhível, alegação e fonte próximas, julgamento depois                            | Selecionada. A ordem móvel acompanha a leitura antes da decisão                    |

As mudanças conservam os componentes e contratos existentes. Não acrescentam uma biblioteca visual, pedidos sequenciais para dados independentes ou cache compartilhado entre organizações. Texto da alegação vem da revisão autorizada; a URL guarda IDs e filtros, sem copiar conteúdo protegido para um estado de longa duração.

## Referências utilizadas

Consulta em 12/10/2026. São referências de interação e verificação; não resultados sobre o EvidenceDesk.

- [WCAG 2.2](https://www.w3.org/WAI/WCAG22/quickref/): reflow, contraste, foco não encoberto, identificação de erros e tamanho mínimo de alvos orientam a matriz de verificação.
- [ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/patterns/): diálogo, retorno de foco e teclado; controles nativos continuam preferidos quando já expressam a operação.
- [Vercel Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md): estado na URL, campos identificados, conteúdo extenso e foco visível orientam a revisão do código.
- [Playwright: acessibilidade](https://playwright.dev/docs/accessibility-testing): axe entra junto com verificações manuais de teclado e leitura; o scan não cobre todos os requisitos.
- [GOV.UK: resumo de erros](https://design-system.service.gov.uk/components/error-summary/): adaptar a identificação da correção junto ao campo e o direcionamento do foco, sem copiar tema ou instalar componentes.
- [GitHub Primer: navegação](https://primer.style/product/ui-patterns/navigation/) e [layout](https://primer.style/product/getting-started/foundations/layout/): preservar o contexto entre lista e detalhe; usar links quando a seleção altera a URL e empilhar o detalhe de forma coerente no móvel.

## Capturas e reprodução

O [manifesto da rodada](evidence/uiux-20261012/manifest.json) identifica fontes congeladas, diffs, builds, runtime, fixture, estado e hashes. A baseline começa em `a5dff4eff965ac31c6410ebe461228dd7596a3ec`. Antes/depois usam os mesmos IDs de incidente, dossiê, revisão, fonte e snapshot; a captura não registra uma nova decisão. As imagens históricas de setembro e a primeira evolução de outubro conservam seus bytes e datas.

| Comparação           | Antes                                                                | Depois                                                              |
| -------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Citação no desktop   | [1440 px](evidence/uiux-20261012/before/citation-1440.png)           | [1440 px](evidence/uiux-20261012/after/citation-1440.png)           |
| Citação no móvel     | [390 px](evidence/uiux-20261012/before/citation-390.png)             | [390 px](evidence/uiux-20261012/after/citation-390.png)             |
| Decisão de revisão   | [1440 px](evidence/uiux-20261012/before/review-1440.png)             | [1440 px](evidence/uiux-20261012/after/review-1440.png)             |
| Workbench no desktop | [1440 px](evidence/uiux-20261012/before/workbench-1440-viewport.png) | [1440 px](evidence/uiux-20261012/after/workbench-1440-viewport.png) |
| Workbench no móvel   | [390 px](evidence/uiux-20261012/before/workbench-390-viewport.png)   | [390 px](evidence/uiux-20261012/after/workbench-390-viewport.png)   |

As imagens do diálogo foram obtidas depois de preencher a justificativa e percorrer os controles por teclado. O formulário ampliado rola internamente para manter o foco visível; nas capturas depois, o título e parte do resumo ficam acima do trecho exibido. O par compara a mesma sequência e revisão, sem afirmar igualdade de rolagem nem mostrar toda a revisão de uma vez.

O roteiro da aplicação continua em [demo](demo.md); a revisão offline, em [evaluation-workbench](runbooks/evaluation-workbench.md). As regressões da interface ficam em `frontend/e2e`; as do HTML local, em `evals/workbench.browser.mjs`. A stack desta rodada tem projeto, tags e volumes próprios, provider desabilitado e portas em loopback. Credenciais, cookies, `.env`, exports privados, traces e logs brutos ficam fora do Git.

## Verificação e limites

Os [resultados e limites](evidence/uiux-20261012/verification.json) registram o que foi executado sobre a fonte final. A matriz cobre 320, 390, 768, 1024 e 1440 CSS px, com texto extenso, vazio, filtro sem resultado, erros, foco, retorno do leitor e revalidação de acesso. Fixtures de transporte são identificadas nos testes; captura da jornada usa API e dados sintéticos reais da stack.

Zoom por CSS e viewport reduzido são verificações de layout. Zoom nativo do navegador e leitura por leitor de tela permanecem não verificados. A tentativa local de instalar Firefox terminou em timeout; não há resultado de um segundo motor. O scan axe é delimitado às páginas e estados registrados, sem certificação universal. Contas controladas por testes não constituem revisão semântica humana, e o modelo real permanece `not_run`.
