# Capturas da interface

## Investigação atual

As imagens [desktop](readme/investigation.png) e [mobile](readme/investigation-mobile.png) mostram o incidente de pagamento, o resumo das avaliações e a fonte selecionada. O seed é fictício: duas divergências pertencem ao mesmo pedido.

Capturas de 18/10/2026 UTC com Chromium, API local e build de produção. O ambiente local usou PostgreSQL 16.15 e pgvector 0.8.6; o Compose do projeto usa PostgreSQL 17.11. Desktop e mobile mostram as viewports completas de 1440 × 1000 e 390 × 844. O [detalhe do resumo no celular](readme/investigation-summary-mobile.png) é um recorte nativo de 358 × 196. [Dimensões, recortes e hashes](readme/capture.json).

## Leitor de citação

![Alegação e fonte do pedido sintético no leitor móvel](readme/citation-mobile.png)

O leitor mostra a alegação da revisão junto ao texto da fonte. A [demo](demo.md) apresenta o caso de pagamento; o [guia do frontend](frontend.md) descreve navegação, recortes e autorização.

## Inventário de setembro

As **17 capturas históricas de setembro** mostram a aplicação com dados sintéticos. Identidades, snapshots, usuários, horários e estados pertencem às respectivas execuções. Uma imagem corrente não altera os resultados de aprovação, restauração ou conciliação desses registros. Os ícones da stack e separadores SVG do README são recursos gráficos.

| Conjunto                                                                                  | Quantidade | Tratamento                                                                                                                                                              |
| ----------------------------------------------------------------------------------------- | ---------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Divergências](images/workspace-desktop.png) e [texto da fonte](images/source-mobile.png) |          2 | Recortes da aplicação com a conta sintética Ana.                                                                                                                        |
| [Texto JSON da fonte](images/source-json-mobile.png)                                      |          1 | Recorte de 288 × 377 px, obtido diretamente do leitor.                                                                                                                  |
| [Jornada de pagamento](demo.md)                                                           |          8 | Capturas da execução de 22/09 preservadas; sete hashes conferidos no registro de navegador e um no registro de recorte. Inclui dois recortes declarados, sem redesenho. |
| [Revisão e restauração](restore-read-story.md)                                            |          6 | Provas históricas preservadas e seis hashes conferidos no manifesto da rodada.                                                                                          |

O [inventário inicial](evidence/screenshots-20260922.json) conserva hashes, dimensões e origens dos 16 arquivos anteriores ao recorte de JSON. Os registros da [jornada de pagamento](demo.md) e da [restauração](restore-read-story.md) identificam as fontes e os resultados funcionais de cada execução. Aprovação por contas operadas por automação verifica o fluxo; não equivale a avaliação semântica humana.

Capturas extensas das execuções históricas aparecem como links. Os recortes vêm do navegador ou do registro nativo documentado, com o texto e os dados daquela execução.

## Workbench de avaliação de 12/10/2026

As capturas [desktop](evidence/evolution-20261012/workbench-desktop.png), [móvel](evidence/evolution-20261012/workbench-mobile.png) e [ensaio de ampliação](evidence/evolution-20261012/workbench-zoom-200.png) mostram o HTML offline de revisão semântica. Não são telas da aplicação autenticada de incidentes. A fixture expõe três respostas, fontes congeladas e texto hostil tratado como conteúdo; o aviso “Gate humano inconclusivo” permanece visível.

O [recibo de navegador](evidence/evolution-20261012/browser.json) identifica os procedimentos. As imagens permitem conferir conteúdo e disposição dos controles; sozinhas não comprovam zoom nativo, execução segura do texto hostil ou qualidade do julgamento humano. Os arquivos longos devem ser abertos no tamanho original para ler os campos.

## Reproduzir a leitura

Com a aplicação e o seed local disponíveis, a partir de `frontend`:

```powershell
$env:ED_E2E_BROWSER_CHANNEL = 'msedge'
$env:ED_E2E_BASE_URL = 'http://127.0.0.1:3106'
$env:ED_E2E_ARTIFACT_DIR = Join-Path $env:TEMP 'evidencedesk-capturas'
npm run test:e2e -- json-syntax.spec.ts visual.spec.ts
```

A saída fica fora do repositório. Inspecione fonte e texto carregados antes de selecionar capturas; preserve os arquivos vinculados a manifestos históricos. Para outros sistemas, use um navegador instalado compatível com Playwright.
