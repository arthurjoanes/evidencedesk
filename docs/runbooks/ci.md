# Integração contínua

O workflow `.github/workflows/ci.yaml` prepara quatro grupos independentes em runners Ubuntu 24.04. A configuração foi revisada e os helpers foram testados localmente em 21/09/2026. **O workflow ainda não foi executado no GitHub**: não houve push, pull request nem publicação. Testes locais e análise do YAML não provam que o runner remoto passou.

## Verificações e falhas

| Job | Verificação e condição de falha |
| --- | --- |
| `backend-and-operation` | Dependências Python com hashes, Ruff com configuração explícita, Mypy, helpers e pytest sem provedor pago. Banco principal do runner em 5546 e banco de integração/manutenção separado em 5547, ambos migrados. Configurações de observabilidade validadas pelas ferramentas e build da API. |
| `frontend` | Instalação npm pelo lock sem scripts de terceiros, assets locais, tipos, lint, formato, unitários e build. `npm audit --omit=dev --audit-level=high` falha diante de HIGH/CRITICAL ou erro da consulta. |
| `browser-journeys` | Perfil `--e2e` com projeto/volumes próprios, UI3107/API8107 e banco sem porta publicada; chave vazia e provedor desativado impostos pelo override. Seed sintético e `qa-imports` são preparados antes do worker. Playwright Chromium executa as jornadas uma vez, sem retry automático. A leitura de geração Azure existente é ignorada quando seus IDs não foram fornecidos; nenhuma geração paga é admitida. |
| `image-vulnerabilities` | Cada imagem runtime é construída e exportada por identidade; Trivy fixado por digest analisa todas as severidades. O gate reprova qualquer HIGH/CRITICAL, incluindo vulnerabilidades ainda sem correção. Erro do scanner, relatório ausente/incompatível ou ausência de alvos inspecionados também reprovam. |

Os jobs têm tempo máximo e o token GitHub possui apenas `contents: read`. Actions estão fixadas por SHA; credenciais do checkout não são persistidas. Artifacts são conservados por sete dias e coletados também quando uma verificação falha. O encerramento dos projetos de teste roda com `always()`; seus volumes vivem no runner descartável.

## Evidências e dados sensíveis

Os artefatos de navegador contêm apenas dados sintéticos e podem incluir traces de falha. Os de segurança registram a identidade da imagem e o JSON de vulnerabilidades. Trivy usa explicitamente **`--scanners vuln`**: este workflow não executa scanner de segredos. `publish_vulnerability_report.py` publica somente campos permitidos de vulnerabilidades, excluindo configuração/ambiente da imagem, histórico e `Secrets/Match`. A saída intermediária `scan-private/` não entra no artifact. Não ampliar o scanner sem preservar essa separação.

`--exit-code 0` na etapa do scanner permite avaliar o relatório completo no gate seguinte; não transforma findings em aprovação. `scripts/check_vulnerability_report.py` devolve código 1 para HIGH/CRITICAL e 2 para entrada inválida. Nenhum `--ignore-unfixed` ou filtro de severidade remove findings do relatório. A base do scanner é consultada no momento da execução, portanto um artefato que passou anteriormente pode reprovar depois.

## Validação local e limites

Os três testes de `scripts/test_vulnerability_report.py` passaram: alvo limpo válido, HIGH sem versão corrigida e ausência/formato incompatível de relatório. Os helpers passaram Ruff com a mesma configuração do workflow. O YAML foi lido localmente e conferido quanto aos quatro jobs e permissões; isso não substitui a validação do GitHub Actions. O frontend passou 35 unitários, tipos, lint, formato e build, com regressões de navegador registradas em [frontend-review.md](../frontend-review.md).

Uma execução completa deve respeitar o limite real de login das contas demo. Repeti-la várias vezes na mesma instância em quinze minutos pode produzir 429. O CI cria seu próprio projeto e não altera essa política; testes locais dirigidos usam o arquivo pertinente. Seeds e uploads de QA nunca devem ser apontados para dados de produção.

O scan local de 21/09/2026 foi executado depois desta revisão inicial: reprovou API e frontend, motivou correções do runtime frontend e continuou reprovado pelos findings residuais. Consulte [a triagem com identidades, resultados anteriores e corrigidos](../security-image-review-2026-09-21.md). O GitHub Actions permanece não executado. Não há waiver automática para findings sem correção. Alterações no provedor, carga real, Azure hospedado e avaliação humana de conclusões continuam fora deste CI. As jornadas com respostas controladas são identificadas no código e não substituem os testes de autorização e concorrência do backend.

Para repetir o ensaio offline com Trivy e base já disponíveis, a partir da raiz: `python scripts/scan_runtime_images.py --cache-db CAMINHO_PARA_DB --services api frontend --evidence-name NOME_NOVO`. A pasta precisa conter `metadata.json` e `trivy.db`, com base de até 72h. O comando não baixa imagem/base, não reinicia serviços, congela os IDs antes do scan e recusa sobrescrever uma pasta de evidências. Usa até 1 GiB de memória e uma CPU por scanner, uma imagem por vez. A escolha explícita do cache permite usar uma base existente sem alterar seu conteúdo; o comando verifica o hash antes/depois.

Referências oficiais: [Trivy para imagens](https://trivy.dev/docs/dev/guide/target/container_image/), [opções do comando image](https://trivy.dev/docs/dev/references/configuration/cli/trivy_image/) e [códigos de saída](https://trivy.dev/docs/dev/guide/configuration/others/).
