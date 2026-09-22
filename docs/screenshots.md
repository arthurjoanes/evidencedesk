# Capturas da interface

A conferência inicial de 22/09/2026 identificou **16 imagens PNG** reais da aplicação. Depois dela, o leitor recebeu realce sintático de JSON e uma nova captura focada, totalizando **17 imagens** neste inventário. As provas anteriores conservam o leitor monocromático daquela versão. Os ícones da stack e separadores SVG do README são recursos gráficos, não screenshots.

| Conjunto                                                                                           | Quantidade | Tratamento                                                                                                                                                              |
| -------------------------------------------------------------------------------------------------- | ---------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Divergências](images/workspace-desktop.png) e [texto anterior da fonte](images/source-mobile.png) |          2 | Recortes da primeira revisão, com conta sintética Ana. A tabela permanece atual; o JSON monocromático foi preservado como referência anterior.                          |
| [JSON com realce sintático](images/source-json-mobile.png)                                         |          1 | Recorte atual de 288 × 377 px, obtido diretamente do leitor. O [registro](evidence/syntax-highlight-20260922.json) identifica a nova implementação, testes e hash.      |
| [Jornada de pagamento](demo.md)                                                                    |          8 | Capturas da execução de 22/09 preservadas; sete hashes conferidos no registro de navegador e um no registro de recorte. Inclui dois recortes declarados, sem redesenho. |
| [Revisão e restauração](restore-read-story.md)                                                     |          6 | Provas históricas preservadas e seis hashes conferidos no manifesto da rodada.                                                                                          |

Na primeira conferência, as fontes das telas ilustradas e o lockfile do frontend eram iguais entre as bases das duas jornadas e a versão capturada `5c2ed6e`. A inspeção das 16 imagens confirmou aquela estrutura. A alteração posterior de realce sintático modifica a apresentação do leitor, não o texto canônico, os dados ou a regra de negócio; ela tem registro próprio. A tela de login não aparece nessas imagens e não é objeto desta comparação. IDs, usuários, horários e estado dos incidentes pertencem às respectivas execuções; não são comparações de igualdade pixel a pixel nem resultados novos de restauração, aprovação ou IA.

O [inventário inicial verificável](evidence/screenshots-20260922.json) conserva os hashes, dimensões e origens dos 16 arquivos anteriores. A nova rodada passou em `json-syntax.spec.ts` e `visual.spec.ts`, sem falhas ou skips, conferindo preservação do texto selecionado, distinção de cores, formatação reversível, contraste automatizado do trecho, modo de cores forçadas, ausência de overflow global e retorno do foco. Não criou incidentes, dossiês ou chamadas ao provedor.

Os prints longos das execuções históricas aparecem apenas como links. As imagens embutidas no README e nas docs são a tabela, o novo JSON colorido e o detalhe original do snapshot (473 × 582). Os cortes vêm de `locator.screenshot()` ou do registro nativo já documentado; não há reconstrução, substituição de texto ou redesenho de pixels.

## Reproduzir a leitura

Com a aplicação e o seed local disponíveis, a partir de `frontend`:

```powershell
$env:ED_E2E_BROWSER_CHANNEL = 'msedge'
$env:ED_E2E_BASE_URL = 'http://127.0.0.1:3106'
$env:ED_E2E_ARTIFACT_DIR = Join-Path $env:TEMP 'evidencedesk-capturas'
npm run test:e2e -- json-syntax.spec.ts visual.spec.ts
```

A saída fica fora do repositório. Inspecione fonte e texto carregados antes de selecionar capturas; preserve os arquivos vinculados a manifestos históricos. Para outros sistemas, use um navegador instalado compatível com Playwright.

## Limpeza conferida

As 17 imagens possuem referência documental ou vínculo com um manifesto. A nova apresentação conserva somente um recorte móvel do JSON; o arquivo anterior permanece para validar o registro da primeira revisão. Caches, dependências, builds, traces, relatórios temporários e dados locais já estão ignorados pelo Git e foram preservados para execução. O pequeno `experiments/reports/checkpoint-security-tests.log` é uma prova citada por três manifestos; não é um log de sessão descartável. Licenças, dados sintéticos de avaliação e evidências históricas continuam necessários às verificações documentadas.
