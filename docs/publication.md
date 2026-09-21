# Verificação para publicação

Revisão de 21/09/2026. O objetivo é uma entrega de portfólio que outra pessoa consiga instalar, explorar e verificar a partir do repositório. A bancada funciona localmente; Azure OpenAI é opcional, com endpoint e deployment definidos pelo operador.

## Correções da versão

- Evidências derivadas exigem acesso ao incidente de origem. Leituras de ferramentas, citações e despacho aplicam a mesma janela e snapshot.
- Coleções têm paginação real por nome/ID, com cursor vinculado à identidade. A interface permite carregar páginas adicionais.
- Formulários alinham os limites da API, explicam erros, preservam rascunhos e bloqueiam alterações durante uma gravação.
- Azure deixa de depender de um hostname pessoal. A configuração explícita conserva validação HTTPS, domínio de recurso, allowlist atual e proteção da chave no Windows.
- As imagens usam bases atualizadas e OpenSSL corrigido. O CI verifica vulnerabilidades, histórico de segredos e documentação, além do funcionamento.
- O primeiro seed gera a massa sintética ausente. README, arquitetura e capturas passam a pertencer integralmente ao repositório publicável.

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

## Reprodução

O [README](../README.md) contém a instalação da demonstração; o [guia de desenvolvimento](development.md) prepara as dependências e os bancos de teste. O [workflow](../.github/workflows/ci.yaml) usa cinco jobs e permissões somente de leitura. A validação local de sua sintaxe passou.

A [primeira execução remota do CI](https://github.com/arthurjoanes/evidencedesk/actions/runs/35663777096) aprovou backend, frontend, jornadas no navegador e histórico de segredos. Os dois jobs de imagens encontraram uma incompatibilidade do publicador de relatórios com configurações OCI que contêm tanto `rootfs` como `config`. O reconhecimento da configuração foi corrigido, preservando a validação do hash. A regressão reproduziu a falha e passou após a correção, incluindo a rejeição de conteúdo adulterado. As duas rodadas de scripts acima incluem esse teste. Os resultados remotos de cada commit estão nas [execuções do GitHub Actions](https://github.com/arthurjoanes/evidencedesk/actions/workflows/ci.yaml).

O verificador `scripts/check_repository_docs.py` exige que cada link local e imagem pertença ao conjunto publicável. Arquivos presentes apenas em caches, diretórios ignorados ou pastas externas não satisfazem a verificação.

## Limites do resultado

Os dados são sintéticos. Avaliação semântica humana, estudo com analistas, disponibilidade durante 30 dias e recuperação entre hosts continuam exigindo ensaios próprios. O modelo treinado permanece fora do serviço ativo. A aplicação completa ainda não está hospedada no Azure.

A revisão permite avaliar código, comportamento e reprodução desta entrega. Scans e testes têm escopo definido e precisam ser repetidos quando as dependências ou os contratos mudarem.
