# Revisão do frontend — 21/09/2026

Implementação funcional verificada localmente com Next standalone, API, worker, banco e dados demonstrativos reais do projeto. A interface consulta o servidor; não fabrica contas, fontes, aprovações ou resultados de IA. Os ensaios descritos aqui não representam execução do CI nem medição em produção.

## Composição e tarefa principal

Foram comparadas uma bancada com três painéis permanentes e uma região de trabalho com leitor contextual. A segunda preserva largura para tabelas e documentos e permite navegação sequencial no celular. A fila oferece busca, estado e paginação. O incidente conserva escopo, período, cobertura, divergências, timeline, dossiês e fontes. No desktop, o leitor tem divisor ajustável por teclado; no celular, substitui a área de trabalho e mantém o contexto compacto do incidente.

IBM Plex local, superfícies claras, divisórias e seleção azul sustentam uma ferramenta de leitura. Não há gráficos decorativos, contadores inventados ou controles sem operação. Execução de IA, resultado do processamento, suporte de uma alegação e aprovação humana têm estados separados. Uma execução bem-sucedida pode produzir apenas um rascunho ou uma abstenção; isso não é uma conclusão aprovada.

O leitor de `reconciliation_result` apresenta contagens registradas, regra, período, cobertura, lacunas e avaliações incluídas. Não reconcilia eventos nem recalcula valores. Ausência de campo permanece “Não informado”; zero permanece zero. Um formato incompatível ou uma contagem interna contraditória não vira um resumo aparentemente válido: o texto canônico continua acessível com explicação. A formatação opcional de JSON insere somente espaços e quebras, preservando a grafia de números, escapes e chaves duplicadas. O hash sempre se refere ao original.

## Contratos, permissões e dados

- `src/lib/http.ts` centraliza URL relativa, credenciais, CSRF, decodificação validada e erros. Uma resposta 2xx incompatível não vira estado vazio. `src/lib/contracts.ts` valida o contrato recebido com Zod.
- O proxy encaminha apenas à API fixa em `API_INTERNAL_URL`, transmite corpos e SSE, remove cabeçalhos de transporte inadequados e evita cache. A chave Azure permanece fora do navegador.
- `scopeKey` separa o cache por tenant, usuário e sessão; consultas acrescentam incidente, snapshot e recurso. Login, logout e expiração retiram consultas da sessão anterior. O teste de troca Aurora → Horizonte não reaproveitou informação da organização anterior.
- Fontes, revisões, comparação e histórico consultam novamente o backend ao reabrir, com `staleTime: 0` e `gcTime: 0`. Conteúdo antigo fica oculto durante a consulta e depois de erro. Isso fecha a janela em que o cache de 15 segundos poderia reapresentar uma fonte antes da autorização atual; não apaga retroativamente conteúdo já visto.
- O snapshot da citação é independente do snapshot selecionado para o trabalho. Dossiê e revisão são escolhas explícitas na URL; a interface confere a associação ao incidente. O histórico permite consultar revisões anteriores, inclusive a aprovada.
- Importações validam manifesto, nomes, tamanhos e hashes antes do envio, retomam o lote reconhecido pelo servidor e exibem erro por arquivo. Publicação continua atômica: só o estado confirmado `ready` disponibiliza o snapshot.
- Edição manual usa IDs estáveis e `If-Match`. Um conflito mantém o texto preenchido; uma nova revisão preserva a base e o histórico. Aprovação requer permissão, usuário independente e conjunto completo de alegações. Exportação só aparece quando autorizada para a revisão aprovada.
- SSE provoca atualização das consultas; `GET /runs/{id}` permanece a referência, com polling quando o stream falha. Cancelamento aguarda confirmação do servidor. A interface não apresenta uma tentativa atual falha como se fosse o êxito de uma revisão antiga.
- A disponibilidade do índice é consultada ao abrir seu detalhe em Fontes. O servidor informa capacidade, motivo de indisponibilidade, cobertura e job separadamente. A ação só aparece quando habilitada, incompleta e sem job existente; usa CSRF e chave de idempotência por intenção. Um job terminal falho preserva o diagnóstico e a cobertura parcial, sem oferecer uma repetição que o contrato atual não executa. Etapas de investigação e indexação têm rótulos em português.

## Ensaios executados

Comandos executados em `frontend`: `npm run test`, `npm run typecheck`, `npm run lint`, `npm run build` e `npm run format:check`. A versão final passou nos **35 testes unitários**, tipos, lint, build de produção e formatação. O build usa um worker. `npm audit --omit=dev --json` registrou **zero vulnerabilidades de produção** na consulta local; o resultado está em [npm-audit-production.json](../frontend/artifacts/npm-audit-production.json).

Os unitários verificam fronteira HTTP/CSRF e erros, hashes e limites da importação, identidade e relações no diff de alegações, campos ausentes/zero, tipos incompatíveis e contradições da conciliação, preservação lexical do JSON e consistência de cobertura/capacidade do índice. Não são testes do algoritmo de conciliação do backend.

Os E2E foram executados com Playwright e Microsoft Edge headless no laboratório local do projeto, com dados sintéticos. O conector de navegador desta sessão não expôs superfícies disponíveis; as capturas foram produzidas pelo próprio ensaio e inspecionadas visualmente.

| Execução local | Resultado observado |
| --- | --- |
| Seis jornadas principais, início 07:34:00 UTC | **6 passaram em 49,9 s**, sem skips, falhas ou retries: acessibilidade/CSP, falhas de transporte controladas, PDF real, sessão e navegação, revisão manual/exportação e capturas responsivas. |
| Repetição às 07:37:54 UTC | **2 passaram e 5 falharam na entrada**: o limite real de 10 logins em 15 minutos da conta sintética foi acionado. Não é registrado como passe. [Resultado preservado](../frontend/artifacts/e2e-rate-limit-attempt.json). |
| QA direcionado final, início 07:46:18 UTC | **2 passaram em 19,9 s**: leitor estruturado da geração existente e conflito 409 real com preservação do rascunho, nova revisão, segundo revisor e exportação. [Resultado preservado](../frontend/artifacts/e2e-targeted-final.json). |
| Índice, revisão e cache, início 08:27:58 UTC | **2 passaram e 1 falhou no harness em 13,7 s**: índice e revisão manual/exportação passaram na imagem Docker final. O teste de revogação encontrou dois elementos `role=alert`, incluindo o anunciador de rota do Next. [Resultado preservado](../frontend/artifacts/e2e-cache-index-initial.json). |
| Correção da fixture de revogação | A tentativa seguinte detectou que a fixture não fornecia `request_id` e `retryable`, exigidos pelo contrato de erro. A interface exibiu o erro genérico e manteve a fonte oculta; o teste não passou. [Resultado preservado](../frontend/artifacts/e2e-cache-fixture-invalid.json). |
| Revogação direcionada, início 08:29:10 UTC | **1 passou em 3,0 s** após corrigir seletor e fixture. A primeira leitura foi real; a segunda resposta ficou pendente e depois retornou 404 controlado. O texto canônico esteve ausente em ambos os estados. [Resultado preservado](../frontend/artifacts/e2e-protected-source-final.json). |
| Smoke após correção do runtime | **1 passou em 3,5 s** na imagem `7640031e0466…`: entrada real, leitura de fonte e reabertura com recusa controlada, sem texto ou proveniência do cache. [Resultado preservado](../frontend/artifacts/e2e-runtime-hardening.json). |

A revisão direcionada usou dois logins da Ana e um do Bruno após administração local limpar uma vez o registro de limite da conta sintética. O código e a política de autenticação não foram relaxados. A suíte completa deve respeitar a janela de login; repetir várias vezes seguidas não é uma operação neutra.

O teste de PDF criou um lote identificado como QA na coleção isolada `qa-imports`, aguardou o worker publicar, consultou a extração canônica e abriu a página original no canvas do PDF.js. Verificou pixels renderizados e o SHA-256 do conteúdo baixado, sem alterar `commerce-main`.

O ensaio de IA **somente leu** a geração real `2605b0dcf3fd4045a345a51fd2f80bdf`, fornecida pela implementação do backend. Afirmou zero `POST /incidents/{id}/runs`. Foram observadas três alegações em rascunho, sem exportação antes de aprovação, e citação ao agregado determinístico. Os 222 pedidos, 667 observações, 666 eventos e zero divergências vieram do conteúdo autorizado, não de fixtures de interface. Não foi feita nova chamada Azure pelo frontend durante esse ensaio.

`controlled-states.spec.ts`, `index-capability.spec.ts` e `protected-source.spec.ts` usam respostas de transporte controladas e identificadas como fixture para testar falha de execução, capacidade desabilitada, cobertura contraditória e revogação de uma fonte. Essas respostas não são evidência de falhas reais do provedor ou de revogação administrativa executada pelo navegador. Login, primeira leitura da fonte e fluxos de revisão/exportação utilizam a API local real. O índice verificou uma única admissão com CSRF/idempotência, erro preservado, ausência de falsa conclusão e apresentação a 320 px.

## Responsividade, acessibilidade e imagens

Verificados 320, 768 e 1440 px sem overflow horizontal da página; tabelas mantêm região própria de rolagem. Abertura da fonte move o foco ao título; voltar restaura o controle de origem, inclusive depois de mudar do layout desktop para o móvel. O divisor responde às setas do teclado. A CSP teve nonce distinto em duas respostas e não permitiu `unsafe-inline` em scripts.

axe não reportou violações das regras WCAG 2 A/AA e 2.1 AA executadas em login, fila, fonte, apresentação móvel e no novo leitor de conciliação. Isso não substitui uma avaliação completa com leitor de tela e usuários.

- [Fila desktop](../frontend/artifacts/screenshots/queue-desktop.png), [tablet](../frontend/artifacts/screenshots/queue-tablet.png) e [mobile](../frontend/artifacts/screenshots/queue-mobile.png).
- [Incidente desktop](../frontend/artifacts/screenshots/workspace-desktop.png), [mobile](../frontend/artifacts/screenshots/workspace-mobile.png), [fonte tablet](../frontend/artifacts/screenshots/source-tablet.png) e [mobile](../frontend/artifacts/screenshots/source-mobile.png).
- [PDF importado e renderizado](../frontend/artifacts/screenshots/pdf-desktop.png).
- [Resultado real Azure](../frontend/artifacts/screenshots/azure-result-desktop.png), [conciliação estruturada no celular](../frontend/artifacts/screenshots/azure-source-mobile.png) e [JSON formatado no celular](../frontend/artifacts/screenshots/azure-source-json-mobile.png).
- [Falha de execução controlada pelo teste](../frontend/artifacts/screenshots/controlled-failed-run.png).
- [Índice parcial com falha controlada, a 320 px](../frontend/artifacts/screenshots/controlled-index-mobile.png). A captura recorta a região aberta; o ensaio também conferiu ausência de overflow da página e zero violações nas regras axe executadas sobre essa região.

## Avaliação de clean code

A divisão por capacidades corresponde aos fluxos do produto: `incidents`, `evidence`, `dossiers`, `imports`, `timeline` e `identity`. Rotas não contêm regra de negócio de conciliação. A camada HTTP e os contratos são pontos explícitos de entrada, e controles compartilhados permanecem pequenos. `import-files.ts` trata validação e hashing separados da interface; `compareClaims` compara identidade e conteúdo em função pura testável. No leitor, parsing/validação, resumo e apresentação canônica são módulos diferentes por terem responsabilidades diferentes, não por uma meta de quantidade de arquivos.

Durante os ensaios foram corrigidos problemas de comportamento: limpar todo o QueryClient removia o observador da sessão no login; cobertura confundia quantidade de janelas com sistemas; mudança de breakpoint invalidava o elemento de retorno de foco; reabertura de fonte precisava aguardar autorização mesmo com cache recente; minificação do agregado dificultava auditoria no celular. As correções preservam o contrato e são demonstráveis nos fluxos acima. `SnapshotIndex` concentra uma consulta e uma admissão, com schema próprio porque esse contrato tem regras de consistência diferentes do documento fonte; não introduz outro gerenciador de estado.

Há complexidade remanescente: `DossierEditor`, `RevisionView` e `Workspace` coordenam estados de formulário, permissões e consultas em componentes extensos. As fronteiras estão legíveis, mas uma nova família de decisões de revisão justificará extrair seções com estado próprio. O contrato Zod é mantido manualmente em paralelo ao contrato Python; mudanças exigem revisão conjunta e testes. Não há justificativa para acrescentar agora uma camada genérica de repositórios, um segundo gerenciador de estado ou abstrações de formulário que ocultem o domínio.

## Limites conhecidos

### Medição de produção no laboratório

`node scripts/measure-lab.mjs`, executado a partir de `frontend/`, mediu a imagem Docker de produção em Edge headless, viewport1440x1000, cache HTTP do navegador desabilitado e sem limitação artificial de CPU/rede. Usou um login sintético da Carla e apenas leituras, enquanto outras tarefas do host continuavam ativas. [Amostras e recursos por rota](../frontend/artifacts/performance-lab.json).

A medição foi feita na imagem `04eeda744513…`, anterior ao patch de PCRE2 e à remoção das ferramentas de pacote do runtime. Não foi repetida para a imagem `7640031e0466…`; as fontes e versões do aplicativo foram preservadas, mas isso não transforma as amostras anteriores em uma nova medição.

| Medida | Observado |
|---|---|
| JavaScript carregado na fila, corpo codificado |297.979 bytes por navegação; chunks e tamanhos individuais no relatório |
| JavaScript no incidente |316.639 bytes; não inclui o PDF.js carregado sob demanda |
| Conteúdo da fila disponível, três navegações |237–366ms |
| Conteúdo do incidente disponível, três navegações |443–1.011ms |
| LCP observado até conteúdo disponível |168–244ms; o shell pode ser o maior elemento antes do conteúdo remoto |
| Soma de layout shifts sem interação recente |0,0219 na fila;0 no incidente, na janela observada |
| Leitor de fonte de216 caracteres, oito aberturas |47–117ms; heap JS observado30,9–38,6MiB, com redução espontânea durante a série |
| Timeline renderizada |30 linhas da página; paginação limita DOM |

Essas amostras não são percentis de campo nem aprovação de Core Web Vitals. LCP não substitui tempo até dados utilizáveis. A soma de shifts não implementa o algoritmo completo de janelas de CLS. Event Timing registrou três eventos de16ms; isso não mede INP. A amostra pequena de heap não prova ausência de vazamento, e o leitor pequeno não caracteriza PDFs grandes. O teste exercita paginação real, não um stress de milhares de linhas no DOM. Zero investigações ou chamadas Azure foram criadas.

Não foram validados manualmente leitor de tela, Safari/Firefox, impressão, interrupção real do provedor durante cancelamento, nem retomada de upload depois de perda da resposta de criação do lote. O código implementa SSE/polling e cancelamento, mas os cenários de concorrência do worker e consumo do provedor pertencem aos testes do backend. As conclusões da IA não foram aprovadas semanticamente por este QA.

A execução descrita usou HTTP local, credenciais sintéticas e dados de laboratório. Configuração HTTPS/cookie seguro e operação em produção devem ser validadas no ambiente de implantação. A CSP admite estilos inline pelas medidas dos painéis e canvas; scripts usam nonce e o PDF.js carrega assets locais. ESLint 9 permanece por compatibilidade com os plugins do config Next instalado; acompanhar a migração é manutenção explícita. Nenhuma dessas observações é uma certificação de segurança, disponibilidade ou acessibilidade.

O scan posterior motivou atualização de PCRE2 e remoção de npm/npx/Corepack/Yarn do estágio runtime, preservando o aplicativo e o build. Os onze findings HIGH/CRITICAL corrigíveis desapareceram; ainda restam 52 HIGH e 4 CRITICAL sem versão corrigida na base consultada. O gate continua reprovado. Consulte [a triagem e as provas da imagem](security-image-review-2026-09-21.md) antes de interpretar o `npm audit` limpo como ausência de vulnerabilidades do sistema operacional.
