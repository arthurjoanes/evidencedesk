# Frontend

O frontend apresenta incidentes, fontes e revisões confirmados pela API. O backend responde pela conciliação, autorização, publicação de snapshots e decisões de revisão. Uma investigação concluída produz um rascunho; a interface distingue esse resultado de uma revisão humana aprovada.

## Arquitetura

Next.js App Router organiza as rotas; `frontend/src/features` reúne os fluxos de incidentes, fontes, dossiês, importações, coleções e identidade. TanStack Query gerencia os dados remotos. O recorte da investigação, a seleção de fonte e a busca aplicada vivem na URL. Os formulários usam React Hook Form e Zod, com mensagens locais de validação.

`frontend/src/lib/http.ts` concentra URLs relativas, credenciais de mesma origem, CSRF, erros e validação das respostas. O proxy do servidor encaminha somente à API configurada; credenciais do provedor de IA ficam no servidor. A CSP recebe nonce por resposta. Scripts, fontes IBM Plex e assets PDF.js são servidos localmente; PDF.js é carregado ao abrir uma página PDF.

## Autorização e cache

As chaves do cache incluem organização, usuário e sessão, além do recurso e snapshot. Login, logout e expiração removem consultas da sessão anterior. Fontes, revisões, histórico e comparação aguardam a autorização atual ao reabrir; o conteúdo permanece oculto durante a consulta e depois de uma recusa.

Revalidar a sessão oculta o conteúdo e suspende os diálogos. Se o acesso continua válido na mesma sessão, o formulário preserva o trabalho na mesma janela. Substituição ou encerramento da sessão descarta o estado protegido.

A referência da citação conserva o snapshot, o dossiê, a revisão e a alegação que a originaram. O leitor confere esses IDs, o vínculo entre alegação e fonte e a autorização atual antes de apresentar o contexto e o conteúdo citado. Alterar o recorte da bancada mantém a referência do dossiê anterior. A busca aplicada de fontes permanece na URL ao trocar de aba, voltar ou recarregar.

## Investigação e revisão

SSE invalida consultas, e `GET /runs/{id}` permanece a referência do estado da execução. Polling mantém a atualização quando o stream falha; cancelamento depende de confirmação do servidor. O índice apresenta capacidade, cobertura e execução separadamente, incluindo estados de processamento parcial.

Edições preservam IDs de alegações e usam `If-Match`. Um conflito conserva o rascunho para que o usuário compare a revisão atual antes de reenviar. Os formulários ficam bloqueados durante a gravação para que uma resposta lenta não descarte alterações posteriores ao envio. O dossiê e a justificativa de revisão protegem trabalho não salvo ao fechar ou recarregar.

O diálogo de revisão mostra as alegações da versão selecionada e suas fontes. A decisão começa sem seleção. Aprovar exige conferir cada alegação e escrever uma justificativa; uma abstenção sem alegações exige confirmar a abstenção e as lacunas. Solicitar ajustes se aplica a todas as alegações daquela revisão, incluindo as ainda não conferidas. O backend valida a decisão, a autoria e a revisão esperada.

## Fontes e importações

A lista de coleções usa cursor do servidor e permite carregar mais resultados, inclusive quando o total é desconhecido. Importações conferem manifesto, limites, nomes, tamanhos e hashes no navegador, enviam os arquivos ao backend e aguardam publicação confirmada. A retomada na mesma janela consulta o lote existente e envia os arquivos ainda pendentes.

O leitor de conciliação mostra os valores registrados, a regra e a cobertura. Quando o conteúdo não satisfaz o contrato estruturado, apresenta o original legível. A formatação de JSON preserva números, escapes e chaves duplicadas. O leitor PDF oferece o texto canônico como referência acessível e alternativa à renderização visual.

## Desenvolvimento e verificações

Use Node.js 24. Na pasta `frontend`, instale as dependências do lock e prepare os assets locais:

```powershell
npm ci --ignore-scripts
npm run prepare:assets
```

Com a API em execução, `npm run dev` inicia a interface local. `API_INTERNAL_URL` configura o endereço da API somente no servidor. Para verificar o frontend e construir o artefato de produção:

```powershell
npm run typecheck
npm run lint
npm run format:check
npm run test
npm run build
```

Os testes unitários cobrem a fronteira HTTP, isolamento de sessão, navegação, validação de importações, leitura da conciliação, contexto de citação e requisitos de revisão. Os contratos de formulário validam limites de texto e listas, além de rejeitar resultados com evidências sem alegações citadas. Consulte o [guia de execução](../frontend/README.md) para o servidor standalone e a organização das pastas.

## Jornadas de navegador

As jornadas Playwright ficam em `frontend/e2e`. O [runbook de CI](runbooks/ci.md) descreve como preparar API, worker, seed e coleção `qa-imports` em projetos isolados. Os testes de escrita exigem dados sintéticos e uma stack própria.

Execute a suíte em dois grupos, cada um com um namespace Compose novo e seu próprio banco recém-preparado. Construa as imagens uma vez e reutilize as mesmas imagens nos dois projetos. As portas do perfil E2E podem ser usadas em sequência, encerrando o grupo anterior antes de iniciar o próximo.

O controle real admite até 10 tentativas de login por e-mail em 15 minutos, incluindo acessos bem-sucedidos e substituição de sessão. `stop` preserva os volumes; reutilizar o nome do projeto também reutiliza o banco e seu histórico de tentativas. Prepare outro nome para uma nova rodada e evite logins manuais adicionais no banco dos testes.

Na pasta `frontend`, instale Chromium com `npx playwright install chromium`. Configure `ED_E2E_BASE_URL` para o runtime do grupo e `ED_E2E_ARTIFACT_DIR` para uma pasta privada fora do Git:

| Comando                    | Grupo                                                                    |
| -------------------------- | ------------------------------------------------------------------------ |
| `npm run test:e2e:core`    | Jornadas gerais de investigação, importação, sessão e autorização.       |
| `npm run test:e2e:stories` | Pagamento e regressões de revisão e citação. Exige `ED_PAYMENT_STORY=1`. |

Confira a seleção sem autenticar com `npm run test:e2e:core -- --list` e `npm run test:e2e:stories -- --list`. O grupo `core` exclui os títulos das jornadas selecionadas em `stories`; revise os seletores do `package.json` ao acrescentar ou renomear esses testes. A configuração padrão executa cada teste uma vez, sem retry automático.

`existing-run.spec.ts` e as jornadas de restauração são opcionais e exigem seus próprios IDs e configuração. Registre os casos ignorados como cobertura não executada. Ativar casos opcionais que usam a mesma conta exige outro grupo isolado para respeitar a janela de login. `npm run test:e2e` permanece disponível como comando bruto de toda a suíte; executar todas as jornadas rapidamente em um único banco ultrapassa o limite de login.

| Jornada                                                          | O que verifica                                                                                                                                                          |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `investigation.spec.ts`                                          | Login e troca de organização; navegação; retorno de foco; dossiê manual; conflito real entre revisões; segundo revisor; exportação autorizada.                          |
| `import-pdf.spec.ts`                                             | Upload PDF real, publicação pelo worker, texto extraído, pixels no canvas e hash do original.                                                                           |
| `accessibility.spec.ts` e `visual.spec.ts`                       | Regras axe, nonce distinto por resposta, divisor por teclado, apresentação responsiva e retorno do leitor móvel.                                                        |
| `protected-source.spec.ts` e `session-revalidation.spec.ts`      | Ocultação de conteúdo durante consulta e depois de recusa; preservação do trabalho após revalidação da mesma sessão.                                                    |
| `review-regressions.spec.ts` e `publication-regressions.spec.ts` | Contexto da fila; formulários e erros acessíveis; revogação; paginação de coleções; bloqueio de controles durante gravações lentas.                                     |
| `controlled-states.spec.ts` e `index-capability.spec.ts`         | Falha de transporte, capacidade do índice, cobertura parcial e estados sem conclusão confirmada.                                                                        |
| `existing-run.spec.ts`                                           | Leitura opcional de uma geração já concluída; não admite uma nova execução de IA.                                                                                       |
| `payment-story.spec.ts` e `uiux-regressions.spec.ts`             | Pagamento e snapshot reais; revisão independente; decisão explícita por alegação ou abstenção; busca persistente; citação autorizada e foco após histórico/revalidação. |

Paginação com mais de cem coleções, falhas, revogações e estados do índice incluem respostas controladas identificadas no código. Esses cenários verificam o comportamento da interface diante dessas respostas. Incidentes, dossiês, revisão, exportação e PDF usam a API local. A validação de paginação e ACL da API pertence aos testes de integração do backend.

## Manutenção

Parsing da conciliação, comparação de revisões, hashing de arquivos e construção das URLs são funções separadas e testáveis. Extraia uma seção dos componentes de coordenação quando ela ganhar estado próprio. Os schemas TypeScript e Python são mantidos separadamente; mudanças de limite exigem revisão conjunta e regressões.

Regras axe, teclado e viewports verificam aspectos específicos da acessibilidade. A avaliação com leitores de tela, navegadores adicionais e usuários da operação exige ensaios próprios. Testes da interface também não medem SLO de produção nem qualidade semântica das conclusões. A retomada de importação após perda da resposta inicial foi verificada na mesma janela, com API interceptada no navegador; a recuperação do mesmo lote e de sua reserva foi testada separadamente em PostgreSQL. A chave permanece na instância da tela: recarregar ou fechar a página não oferece retomada persistente. O desempenho de PDFs grandes ainda exige verificação específica.
