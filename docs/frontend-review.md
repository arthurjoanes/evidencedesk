# Revisão do frontend

Revisão de 21/09/2026. O frontend apresenta incidentes, fontes e revisões confirmados pela API. A conciliação, a autorização, a publicação de snapshots e a aprovação permanecem no backend. Uma investigação bem-sucedida produz um rascunho; a interface distingue esse resultado da revisão humana aprovada.

## Arquitetura e escolhas

Next App Router organiza as rotas; `src/features` reúne os fluxos de incidentes, fontes, dossiês, importações, coleções e identidade. TanStack Query gerencia os dados remotos; o recorte da investigação vive na URL. Os formulários usam React Hook Form e Zod, com mensagens locais de validação. Não há um segundo estado global duplicando o cache remoto.

`src/lib/http.ts` concentra URLs relativas, credenciais de mesma origem, CSRF, erros e validação das respostas. O proxy do servidor encaminha somente à API configurada; credenciais do provedor de IA não chegam ao navegador. A CSP recebe nonce por resposta. Scripts, fontes IBM Plex e assets PDF.js são servidos localmente; PDF.js só é carregado ao abrir uma página PDF.

O cache inclui organização, usuário e sessão, além do recurso e snapshot. Login, logout e expiração removem consultas da sessão anterior. Fontes, revisões, histórico e comparação aguardam a autorização atual ao reabrir; dados antigos não aparecem durante a consulta ou depois de recusa. Revalidar a sessão oculta o conteúdo e suspende os diálogos, preservando o trabalho na mesma janela quando o acesso continua válido.

A referência da citação conserva seu próprio snapshot. Alterar o recorte da bancada não altera o dossiê anterior. Edições preservam IDs de alegações e usam `If-Match`; conflito conserva o rascunho. Os formulários ficam bloqueados durante a gravação para que uma resposta lenta não descarte alterações posteriores ao envio. O dossiê e a justificativa de revisão protegem trabalho não salvo ao fechar ou recarregar.

A lista de coleções usa cursor do servidor e permite carregar mais resultados, sem supor que há no máximo cem coleções ou exigir um total conhecido. Importações conferem manifesto, limites, nomes, tamanhos e hashes no navegador, enviam os arquivos ao backend e aguardam publicação confirmada. A retomada na mesma janela consulta o lote existente e envia só os arquivos ainda pendentes.

O leitor de conciliação mostra os valores registrados, a regra e a cobertura. Não recalcula eventos nem inventa números ausentes. Se o conteúdo não satisfaz o contrato estruturado, mantém o original legível. A formatação de JSON preserva números, escapes e chaves duplicadas. O leitor PDF oferece o texto canônico como referência acessível.

SSE invalida consultas, e `GET /runs/{id}` permanece a referência. Polling mantém a atualização quando o stream falha; cancelamento depende de confirmação do servidor. O índice apresenta capacidade, cobertura e execução separadamente, sem confundir processamento parcial com disponibilidade completa.

## Verificação reproduzível

Na pasta `frontend`, execute:

```powershell
npm ci --ignore-scripts
npm run prepare:assets
npm run typecheck
npm run lint
npm run format:check
npm run test
npm run build
```

Os **61 testes unitários** passaram nesta revisão, assim como tipos, lint e formatação. Eles cobrem a fronteira HTTP, isolamento de sessão, navegação, validação de importações, leitura da conciliação, revisão de alegações e limites dos formulários. A atualização dos contratos de formulário inclui vinte fontes e trinta pedidos por alegação, vinte notas por lista, limites de texto e rejeição local de um resultado com evidências sem alegações citadas.

As jornadas Playwright estão em `frontend/e2e`. O [runbook de CI](runbooks/ci.md) descreve como preparar API, worker, seed e coleção `qa-imports` em um projeto isolado. A conta demo possui limite real de login: prefira a regressão afetada ao repetir testes no mesmo laboratório. Nunca aponte os testes de escrita a dados de produção.

| Jornada | O que verifica |
| --- | --- |
| `investigation.spec.ts` | Login e troca de organização; navegação; retorno de foco; dossiê manual; conflito real entre revisões; segundo revisor; exportação autorizada. |
| `import-pdf.spec.ts` | Upload PDF real, publicação pelo worker, texto extraído, pixels no canvas e hash do original. |
| `accessibility.spec.ts` e `visual.spec.ts` | Regras axe, nonce distinto por resposta, divisor por teclado, apresentação a 320/768/1440 px e retorno do leitor móvel. |
| `protected-source.spec.ts` e `session-revalidation.spec.ts` | Ocultação de conteúdo durante consulta e depois de recusa; preservação do trabalho após revalidação da sessão. |
| `review-regressions.spec.ts` e `publication-regressions.spec.ts` | Contexto da fila; formulários e erros acessíveis; revogação; coleção depois da primeira página; bloqueio de controles durante gravações lentas. |
| `controlled-states.spec.ts` e `index-capability.spec.ts` | Falha de transporte, capacidade do índice, cobertura parcial e recusa de apresentar uma falsa conclusão. |
| `existing-run.spec.ts` | Leitura opcional de uma geração já concluída; não admite uma nova execução de IA. Sem os IDs explícitos, é ignorado. |

Paginação com mais de cem coleções, falhas, revogações e estados do índice incluem respostas controladas identificadas no código. Elas comprovam comportamento da interface, não falhas reais de provedor. Incidentes, dossiês, revisão, exportação e PDF usam a API local. A validação de paginação/ACL da API pertence aos testes de integração do backend.

Os resultados de execução e as capturas atuais estão registrados na [auditoria de publicação](publication-frontend.md). As imagens selecionadas são versionadas para aparecer também em um clone novo; relatórios temporários e traces ficam em diretórios ignorados e não são dependências da documentação pública.

## Avaliação de manutenção e limites

A organização por fluxo corresponde ao produto. Parsing da conciliação, comparação de revisões, hashing de arquivos e construção das URLs são funções separadas e testáveis. A seleção compartilhada de coleções elimina duas implementações que antes não alcançavam itens depois do limite inicial.

`DossierEditor`, `RevisionView` e `Workspace` ainda concentram bastante coordenação de interface. Separar uma nova seção quando ela ganhar estado próprio é preferível a abstrair toda a aplicação em um formulário genérico. Os schemas TypeScript e Python são mantidos separadamente; mudanças de limite exigem revisão conjunta e regressões. Os limites corrigidos nesta entrega mostram por que esse cuidado é necessário.

As regras axe executadas, o teclado e as larguras verificadas são evidências delimitadas, não uma certificação completa de acessibilidade. Ainda são úteis avaliação com leitores de tela, navegadores adicionais e usuários da operação. Não foi medido SLO em produção, nem inferida qualidade semântica da IA a partir de testes de interface. A retomada de upload após perda da resposta inicial de criação e o desempenho de PDFs grandes não são garantidos por estes ensaios.

A operação em Azure e a qualidade das conclusões exigem suas próprias evidências. A [auditoria de segurança](publication-security.md) identifica as imagens atuais e seu scan, incluindo o sistema operacional; um `npm audit` limpo não comprova ausência de vulnerabilidades no runtime.
