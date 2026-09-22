# Verificação para publicação

Revisão de 21/09/2026. O objetivo é uma entrega de portfólio que outra pessoa consiga instalar, explorar e verificar a partir do repositório. A bancada funciona localmente; Azure OpenAI é opcional, com endpoint e deployment definidos pelo operador.

## Correções da versão

- Evidências derivadas exigem acesso ao incidente de origem. Leituras de ferramentas, citações e despacho aplicam a mesma janela e snapshot.
- Coleções têm paginação real por nome/ID, com cursor vinculado à identidade. A interface permite carregar páginas adicionais.
- Formulários alinham os limites da API, explicam erros, preservam rascunhos e bloqueiam alterações durante uma gravação.
- Azure deixa de depender de um hostname pessoal. A configuração explícita conserva validação HTTPS, domínio de recurso, allowlist atual e proteção da chave no Windows.
- As imagens usam bases atualizadas e OpenSSL corrigido. O CI verifica vulnerabilidades, histórico de segredos e documentação, além do funcionamento.
- O primeiro seed gera a massa sintética ausente. README, arquitetura e capturas passam a pertencer integralmente ao repositório publicável.
- Tentativas de um e-mail já bloqueado não consomem a quota global de login. A reserva continua atômica, e novas chaves permanecem sujeitas aos limites globais, de cardinalidade e de verificação de senha.

Detalhes: [arquitetura e contratos](architecture-review-publication.md), [interface](publication-frontend.md) e [segurança](publication-security.md).

## Resultados executados

| Verificação | Resultado e escopo |
| --- | --- |
| Backend | **235 testes aprovados**, sem falhas ou skips, PostgreSQL real descartável. Inclui RLS, ACL, importação, concorrência, revisão, retenção e configuração Azure. [JUnit final](evidence/publication/backend-release.xml). |
| Frontend | **61 testes unitários aprovados**, TypeScript, ESLint, Prettier e build. |
| Navegador | **11 jornadas aprovadas**, zero falhas/retries. Uma leitura opcional de geração Azure histórica foi ignorada porque não há esses dados no clone. [Resumo por cenário](evidence/publication-frontend.json). |
| Scripts | **49 testes multiplataforma**: no [Windows](evidence/publication/scripts-windows.json), 48 passaram e um cenário de links simbólicos foi ignorado por falta de permissão; no [Linux](evidence/publication/scripts-linux.json), 42 passaram e os sete cenários exclusivos de DPAPI/PowerShell Windows foram ignorados. A rodada Linux usa o runtime sem root e com filesystem somente leitura. |
| Imagens e dependências | API e frontend: zero vulnerabilidades reportadas na base consultada. `npm audit --omit=dev`: zero findings. Consulte a [cobertura e as identidades do scanner](publication-security.md). |
| Revisão visual | Bancada, fila, leitor de fontes, teclado e larguras 320/768/1440 px conferidos. As [capturas](publication-frontend.md) usam dados sintéticos da aplicação real. |
| Primeira instalação | Uma cópia apenas dos arquivos publicáveis iniciou em volumes novos. Sem `datasets/generated` prévio, o seed criou seis pacotes e carregou 30 incidentes, sem chamar um modelo. |

Os testes que simulam transporte/modelo estão identificados; eles verificam contratos, falhas e autorização. A rodada de publicação não fez nova inferência paga. A execução Azure anterior e os experimentos GPU têm [evidências próprias](verification.md).

A correção posterior de admissão de login passou em cinco [testes de integração com PostgreSQL](../backend/tests/integration/test_login_admission.py). Após dez verificações de senha inválida, 129 rejeições do mesmo e-mail mantiveram a quota global em dez; o login válido de outro tenant foi aceito e elevou o contador a onze. Concorrência no último slot, cardinalidade e proteção de CPU também passaram. Essa rodada direcionada não é somada aos 235 testes da rodada anterior.

## Reprodução

O [README](../README.md) contém a instalação da demonstração; o [guia de desenvolvimento](development.md) prepara as dependências e os bancos de teste. O [workflow](../.github/workflows/ci.yaml) usa seis jobs e permissões somente de leitura. A validação local de sua sintaxe passou.

A [primeira execução remota do CI](https://github.com/arthurjoanes/evidencedesk/actions/runs/35663777096) aprovou backend, frontend, jornadas no navegador e histórico de segredos. Os dois jobs de imagens encontraram uma incompatibilidade do publicador de relatórios com configurações OCI que contêm tanto `rootfs` como `config`. O reconhecimento da configuração foi corrigido, preservando a validação do hash. A regressão reproduziu a falha e passou após a correção, incluindo a rejeição de conteúdo adulterado. As duas rodadas de scripts acima incluem esse teste. Os resultados remotos de cada commit estão nas [execuções do GitHub Actions](https://github.com/arthurjoanes/evidencedesk/actions/workflows/ci.yaml).

O verificador `scripts/check_repository_docs.py` exige que cada link local e imagem pertença ao conjunto publicável. Arquivos presentes apenas em caches, diretórios ignorados ou pastas externas não satisfazem a verificação.

A [execução remota após a correção OCI](https://github.com/arthurjoanes/evidencedesk/actions/runs/35666019875) aprovou os seis jobs. Ela precede a correção de admissão de login; cada revisão posterior tem sua própria execução no GitHub Actions.

## Complemento operacional de 22/09/2026

A [história de revisão e recuperação](restore-read-story.md) acrescenta três jornadas reais de navegador e seis capturas: aprovação por conta distinta, conflito HTTP 409 com rascunho preservado e leitura após restauração com a exclusão ainda efetiva. O backup tinha 109 objetos; o destino validou 108 referências após aplicar o ledger atual, de 0 para 1. Fonte, original e dossiê excluídos responderam HTTP 404; o provedor permaneceu em zero chamadas. São dados sintéticos e contas operadas pelo teste, sem avaliação humana da qualidade semântica.

O [manifesto](evidence/restore-read-story/20260922T072246Z-492911fe/manifest.json) associa imagens, comandos, hashes e limites. A prova compara 17 tabelas de domínio e `provider_calls`, além do checkpoint do ledger, durante a janela de leitura. Não compara todo o banco nem demonstra recuperação fora deste computador. Os 54 testes host dessa entrega tiveram 53 passes e um skip Windows; não são somados aos resultados históricos acima. O executor público completo foi preparado depois da execução e tem essa limitação declarada.

O [pacote de avaliação semântica](../evals/human-review/README.md) organiza 60 casos de desenvolvimento, fontes e rubrica para uma rodada futura. Não contém participantes, julgamentos ou ganho de produtividade medido.

A [checagem de segredos da entrega](evidence/restore-read-secret-scan.json) passou sobre os arquivos publicáveis. Dois hashes de fontes foram reconhecidos como falsos positivos e receberam exceções restritas à regra, ao caminho e aos valores exatos; uma chave sintética diferente no mesmo caminho continuou sendo detectada. Esse scan local não substitui a verificação do histórico pelo CI.

## Limites atuais

Os dados são sintéticos. Avaliação semântica humana, estudo com analistas, disponibilidade durante 30 dias e recuperação entre hosts continuam exigindo ensaios próprios. O modelo treinado permanece fora do serviço ativo. A aplicação completa ainda não está hospedada no Azure.

A revisão permite avaliar código, comportamento e reprodução desta entrega. Scans e testes têm escopo definido e precisam ser repetidos quando as dependências ou os contratos mudarem.
