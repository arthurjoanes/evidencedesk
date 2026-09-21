# EvidenceDesk — frontend

Bancada de investigação construída em Next.js App Router. A API Python continua responsável por autorização, conciliação, publicação e decisões. Esta aplicação apresenta o estado confirmado pelo servidor.

## Executar

Use Node.js 24 e a API do projeto em execução. Na pasta `frontend`:

```powershell
npm ci --ignore-scripts
npm run prepare:assets
npm run dev
```

Abra `http://127.0.0.1:3106`. `API_INTERNAL_URL` é uma variável somente do servidor; seu padrão local é `http://127.0.0.1:8106`. No Compose aponta para `http://api:8106`. Não coloque chaves Azure em variáveis `NEXT_PUBLIC_*`.

Para testar o artefato de produção:

```powershell
npm run build
npm start
```

O script de start prepara os arquivos estáticos do standalone e escuta em `127.0.0.1:3106`. `PORT` e `FRONTEND_HOST` permitem configuração explícita. O Dockerfile usa diretamente `server.js`, usuário sem privilégios e porta 3106; a composição completa fica em `../infra/compose`.

A imagem final preserva Node e retira npm/npx/Corepack/Yarn; instalação e build acontecem no estágio anterior. Há patch explícito de PCRE2 pelo repositório Bookworm security. Essa redução não elimina todos os findings da base: o [scan e a triagem](../docs/security-image-review-2026-09-21.md) registram gate reprovado e limites para produção.

O seed e as contas demonstrativas estão documentados no projeto principal. O frontend não cria contas, resultados de IA nem uma sessão fictícia.

## Organização

- `src/app`: rotas, layout, estilos e proxy da API.
- `src/features`: incidentes, registros, fontes, dossiês, identidade e importações.
- `src/lib`: contratos validados, fronteira HTTP, sessão e apresentação de valores.
- `src/components`: controles pequenos e estados compartilhados.
- `e2e`: jornadas contra API real e verificações de apresentação.
- `scripts`: preparação de assets e execução do standalone.

TanStack Query separa o cache por organização, usuário, sessão e snapshot. O estado relevante da investigação vive na URL. O leitor consulta o snapshot da citação; trocar o snapshot do trabalho não reescreve um dossiê anterior. A seleção de dossiê e revisão é explícita e o histórico permite voltar à revisão aprovada.

Leitor, revisões, comparação e histórico aguardam a autorização atual ao reabrir, sem reapresentar conteúdo do cache durante a consulta ou após uma recusa. Isso não apaga retroativamente o que já foi visto. A área de fontes também consulta a disponibilidade do índice: a ação de prepará-lo depende da capacidade informada pelo servidor, e progresso parcial permanece distinto de cobertura completa.

A edição preserva IDs de alegações, usa `If-Match` e mantém o rascunho após conflito. Execuções e exportações usam chaves de idempotência por intenção. O stream invalida consultas; o estado confirmado de `GET /runs/{id}` é a referência, com polling quando o stream não está disponível.

## Verificar

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```

Os E2E exigem API, worker, seed e frontend reais. Eles criam recursos identificados como QA no tenant demonstrativo. O teste de PDF exige uma coleção isolada `qa-imports` no tenant Aurora, autorizada para Ana e Bruno, para preservar a coleção principal.

O workflow prepara essa coleção pelo script `scripts/prepare_e2e.py` e roda as jornadas uma vez em um projeto Compose isolado, sem provedor pago. Os testes de revogação e estados do índice usam respostas controladas identificadas no código; eles verificam comportamento da interface, não demonstram uma falha real do serviço. Consulte o [runbook de CI](../docs/runbooks/ci.md) para gates e limites.

```powershell
npx playwright install chromium
npm run test:e2e
```

É possível usar um navegador instalado: `$env:ED_E2E_BROWSER_CHANNEL='msedge'`. A base é `http://127.0.0.1:3106`; `ED_E2E_BASE_URL` permite outro laboratório. Capturas ficam em `artifacts/screenshots`; traces de falha e relatórios temporários ficam fora do Git. Não execute os testes de escrita sobre dados reais.

`existing-run.spec.ts` é opcional: informe `ED_E2E_EXISTING_RUN_ID` e `ED_E2E_EXISTING_INCIDENT_ID` de uma geração já concluída para testar leitura e citações. O ensaio não admite uma nova geração. Sem esses valores ele é explicitamente ignorado. A conta demonstrativa está sujeita ao limite real de login; execuções completas repetidas dentro de 15 minutos podem receber 429. Use `npm run test:e2e -- nome.spec.ts` para a regressão afetada e respeite a janela, sem reduzir a política do servidor.

## Dependências e limites

Next 16 / React 19, TypeScript 6, Tailwind 4, Radix, TanStack Query/Table, React Hook Form/Zod e PDF.js têm versões exatas no lock. ESLint 9.39.5 foi mantido porque os plugins distribuídos pelo config do Next instalado ainda declaram suporte até a versão 9; acompanhar a migração desse conjunto é uma manutenção pendente. Primitivos Radix e CSS de domínio são locais; `components.json` descreve a configuração compatível com shadcn, sem acrescentar um segundo framework de componentes.

PDF.js é carregado apenas quando a página PDF é solicitada. Worker, fontes padrão, CMaps e WASM são servidos localmente. O texto canônico continua sendo a referência acessível e o fallback quando a renderização falha. Não há OCR no navegador nem destaque aproximado de citação.

Agregados de conciliação possuem leitura estruturada com valores registrados, cobertura e avaliações incluídas; nenhum número é recalculado. O JSON original continua disponível. A formatação opcional altera somente espaços e quebras visuais, preservando a representação de números e escapes.

IBM Plex Sans/Mono são distribuídas sob SIL Open Font License; PDF.js sob Apache 2.0. `prepare:assets` copia assets e licenças das versões instaladas para `public`; esses arquivos gerados ficam fora do Git. Bibliotecas auxiliares do PDF preservam seus arquivos de licença nas mesmas pastas. Scripts de instalação de terceiros não são necessários ao fluxo documentado.

A CSP usa nonce por resposta para scripts, o que exige renderização dinâmica das páginas. Estilos inline permanecem permitidos para medidas dos painéis e do canvas; JavaScript inline sem nonce não é permitido. CSP, escaping e cookies não substituem autorização no servidor.

Consulte [a revisão do frontend](../docs/frontend-review.md) para evidências de testes e limites observados. Resultados locais não representam SLO de produção, validação humana de conclusões ou certificação completa de acessibilidade.
