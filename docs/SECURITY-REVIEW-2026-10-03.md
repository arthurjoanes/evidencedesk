# Revisão de segurança do EvidenceDesk

Em 3 de outubro de 2026, a revisão encontrou dependências desatualizadas e uma configuração que permitia usar cookies e segredos de demonstração com uma origem externa. As correções foram verificadas na árvore de trabalho antes da publicação no Git. O laboratório passou nos testes abaixo; a exposição pública continua sujeita aos requisitos do [perfil hospedado](runbooks/azure-hosted.md).

O escopo inclui os 18 itens legíveis da imagem fornecida, código, configurações, histórico Git, dependências e duas imagens runtime reconstruídas. O item 19 da imagem está vazio. A referência Git é `89add40d0dd8341e7135d2cff32f957f82f15beb`, com as alterações locais identificadas pelos hashes no [registro da execução](evidence/security-review-20261003/summary.json).

## Correções

- Next.js e `eslint-config-next` passaram de `16.3.5` para `16.3.8`. O [aviso do fornecedor](https://github.com/advisories/GHSA-vcvr-r3jv-pc5j) afeta `ImageResponse` em Node quando recebe SVG controlado por um atacante. Esse caminho não foi encontrado na aplicação, mas a versão instalada estava na faixa vulnerável.
- PyJWT passou de `2.14.0` para `2.15.1` nos locks de execução e testes, com hashes dos pacotes preservados. A dependência chega pelo SDK de identidade Azure. O [aviso do fornecedor](https://github.com/advisories/GHSA-42vr-xj54-vc7v) trata de payload recursivo antes da verificação; a sessão da aplicação usa um token opaco.
- A configuração agora recusa origens externas sem HTTPS, cookie Secure, segredos próprios de métricas/cursor com ao menos 32 caracteres e uma senha de banco diferente do exemplo. A API valida isso antes de aceitar requisições. O seed recusa criar contas públicas de demonstração quando há uma origem externa. O login e a autenticação também recusam contas com domínio `.demo` nesse perfil, incluindo sessões criadas antes da mudança de origem.
- O build frontend agora fixa OpenSSL `3.5.9-r0`. O repositório Alpine já não disponibilizava o pin anterior `3.5.8-r0`; a reconstrução confirmou a instalação do novo par `libcrypto3`/`libssl3`.

## Controles por item da imagem

| Item | Resultado | Evidência e alcance |
| --- | --- | --- |
| 1 Env exposta | Verificado | Somente exemplos públicos estão versionados. Gitleaks examinou 23 commits e o snapshot dos arquivos publicáveis, sem achados com as exceções específicas já existentes. Arquivos privados ignorados não entram nesse snapshot. |
| 2 Validação frontend | Verificado | Zod, React Hook Form e validação dos arquivos em `frontend/src/features/imports/import-files.ts`; 66 testes frontend passaram. O backend também valida os pedidos. |
| 3 Validação backend | Verificado | Contratos Pydantic com campos limitados e campos extras rejeitados; JSON limitado a 512 KiB e prazo de leitura. Regressões de corpo, extração, contratos e workflows passaram. |
| 4 SQL injection | Verificado | Valores entram por parâmetros SQLAlchemy. Identificadores interpolados vêm de listas internas fixas; o navegador e o modelo não escolhem SQL. |
| 5 Autenticação fraca | Corrigido no escopo local | Argon2, contas habilitadas, sessão opaca, expiração e logout já existiam. A configuração e o seed recusam combinações inseguras com origens externas; login e sessões existentes de contas `.demo` ficam bloqueados nesse perfil. SSO/MFA hospedado permanece fora da demonstração. |
| 6 IDOR | Verificado | Tenant deriva da sessão; ACL de coleção/incidente, RLS e autorização das evidências. Integrações com tenants distintos e revogação passaram. |
| 7 Senhas no banco | Verificado | `password_hash` contém Argon2. A senha pública do seed é de demonstração; o seed externo e o acesso remoto dessas contas são recusados. |
| 8 Força bruta | Verificado | `identity/admission.py` reserva tentativas atomicamente no PostgreSQL antes do Argon2, com limites globais e por conta. Testes de admissão concorrente passaram. |
| 9 Bloqueio durante envio | Verificado | Formulários desabilitam ações durante envio. Upload possui reserva, slots e revalidação; jobs/revisões usam idempotência ou controle de versão. Testes de concorrência passaram. |
| 10 CSRF | Verificado | Login exige Origin autorizado; mutações autenticadas exigem Origin e token CSRF da sessão. Testes de rejeição passaram. |
| 11 Upload sem validação | Verificado | Allowlist de extensão/MIME, nomes sem caminho, tamanho/hash, quotas, prazo e parser separado. Não há importação de URL ou ZIP. Testes de uploads e extração passaram. |
| 12 Erros revelam informações | Verificado | Respostas genéricas, identificador da requisição e mensagens de validação sem eco do valor recebido. A configuração também oculta seus inputs nos erros. |
| 13 Dependências vulneráveis | Corrigido com pendência | Auditorias Python e npm de produção sem achados; Trivy sem achados nas duas imagens novas. `braces@3.0.3` ainda aparece no ESLint, conforme a pendência abaixo. |
| 14 Tokens mal otimizados | Verificado | Sessão aleatória, hash no banco e validade de 1 a 24 horas. Para IA há limites de entrada/saída, reserva e orçamento mensal, inclusive resultado desconhecido. Tokens de sessão não ficam em localStorage. |
| 15 Rate limit | Verificado no laboratório | Limites persistentes de login, admissão de jobs/SSE/uploads e concorrência do servidor. Uma implantação pública ainda exige dimensionar proteção de entrada e réplicas. |
| 16 Dados sensíveis expostos | Verificado no escopo | Objetos privados, leituras autorizadas, ausência de links públicos permanentes e allowlist de telemetria. Exportação exige revisão aprovada. Não houve teste com dados reais. |
| 17 SSRF | Verificado | Endpoint Azure HTTPS com allowlist exata; serviço ML interno fixo e `trust_env=False`; contratos não oferecem URL/SQL/comando ao modelo. Egress hospedado permanece uma exigência operacional. |
| 18 Cookies inseguros | Corrigido | Cookie HttpOnly, SameSite=Lax e caminho `/api/v1`. HTTP sem Secure é permitido somente para origens de loopback; HTTPS exige Secure. Regressões da configuração passaram. |

## Verificações realizadas

| Verificação | Resultado desta rodada |
| --- | --- |
| Backend e PostgreSQL descartável | 298 testes passaram, sem skips. [JUnit](evidence/security-review-20261003/backend.xml). Sem chamadas ao provedor Azure. |
| Frontend | 66 testes passaram; typecheck, ESLint, Prettier e build de produção passaram no host. |
| Scripts de operação | 88 casos: 86 passaram e dois foram ignorados por condições de plataforma. |
| Código Python | Ruff passou; 115 arquivos formatados; Mypy passou em 75 módulos; `pip check` passou. |
| Dependências | `pip-audit` nos dois locks sem vulnerabilidades conhecidas; `npm audit --omit=dev` sem achados. [Audit completo](evidence/security-review-20261003/npm-full.json). |
| Imagens reconstruídas | API e frontend construídos com tags separadas da demonstração. Trivy 0.74.0, base baixada em 03/10/2026, todas as severidades, somente scanner de vulnerabilidades: [API](evidence/security-review-20261003/api-vulnerabilities.json) e [frontend](evidence/security-review-20261003/frontend-vulnerabilities.json), ambos sem achados. |
| Smoke das imagens novas | API live/ready, frontend e proxy responderam 200; sessão anônima recebeu 401. [Resultados HTTP](evidence/security-review-20261003/runtime-smoke.json). |
| Segredos | Histórico com 23 commits sem achados; [snapshot publicável](evidence/security-review-20261003/gitleaks-publicable.json) sem achados. Nenhuma exceção nova foi criada. |

O PostgreSQL de testes usou a porta 5547 e um container novo. O banco da demonstração na porta 5546 e as imagens de demonstração não receberam essas alterações. O build inicial frontend falhou pelo pin Alpine indisponível; passou após a atualização. O primeiro scan do snapshot usou caminhos absolutos e não reconheceu sete exceções existentes para hashes e endereço de probe; a execução com caminhos relativos passou sem ampliar as exceções.

## Verificação complementar do CI

A continuação encontrou uma incompatibilidade no job de backend: a senha pública do banco de teste era recusada pelos novos testes do perfil externo. O workflow agora usa uma credencial explícita de fixture, igual no Compose e nas três URLs de aplicação. Os três testes de identidade passaram com essa configuração em um PostgreSQL descartável. A senha é um valor público de teste, não uma credencial de implantação.

Ruff conferiu os 152 arquivos Python cobertos pelo CI e mypy aprovou 75 fontes com a configuração do projeto. Em Linux, os 88 testes de scripts tiveram 81 aprovações e sete skips exclusivos de Windows/DPAPI. Os dois casos de symlink ignorados no Windows passaram em Linux; os sete casos Windows já haviam passado na execução anterior.

O navegador Edge 154, conduzido pelo Playwright 1.63 com um worker e sem retries, aprovou os 13 casos ativos da suíte de CI em 48,7 segundos. Cinco casos condicionais exigiam fixtures explícitas de geração existente, pagamento, aprovação/conflito ou restauração. A jornada adicional de pagamento manual passou separadamente em 12,4 segundos: duas fontes reais do laboratório, download com hash e tamanho conferidos, recusa de autorrevisão, revisão por outra conta e exportação. Quatro casos continuam fora dessa execução por exigirem geração ou fixtures de captura/restauração existentes.

Essas jornadas usaram as mesmas imagens examinadas pelo Trivy, um namespace próprio e dados sintéticos gerados pelo código atual. A primeira carga recusou corretamente um dataset local antigo por conflito de metadados; esse dataset foi preservado e a nova geração ficou fora do repositório. A primeira tentativa da jornada adicional atingiu o limite de dez acessos da conta, já consumido pela suíte. O teste separado passou após preparar somente os contadores do banco descartável; os limites da aplicação foram mantidos. Os recibos distinguem as duas tentativas.

Não houve requisição de geração nem chamada ao provedor de IA. O namespace, os containers e os quatro volumes criados para o teste foram removidos. A [prova complementar](evidence/security-review-followup-20261003/summary.json) referencia o [resultado de navegador](evidence/security-review-followup-20261003/browser.json), a [jornada de pagamento](evidence/security-review-followup-20261003/payment-story.json), o JUnit de identidade e os checks de qualidade.

## Pendência de desenvolvimento

O [aviso de braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) não tem versão corrigida publicada nesta data. O audit completo reporta cinco entradas HIGH da mesma cadeia: `eslint-config-next`, plugin Next, `fast-glob`, `micromatch` e `braces`. Elas pertencem à ferramenta de lint. Os padrões do lint vêm da configuração mantida no repositório; não recebem entradas do usuário da aplicação. As duas imagens runtime novas não incluem essa cadeia.

Essa condição limita o uso da ferramenta com padrões não confiáveis. Não foi aplicado downgrade incompatível nem supressão do aviso. A versão publicada pelo fornecedor precisa ser reavaliada quando houver correção.

## Revisão de texto

A skill Humanizer 3.1.0 foi aplicada em modo arquivo ao README, à política de segurança, ao modelo de ameaças e a este relatório. A revisão reduziu legendas redundantes e linguagem sobre o próprio documento. Comandos, blocos de código, destinos dos links, números e evidências históricas foram preservados.
