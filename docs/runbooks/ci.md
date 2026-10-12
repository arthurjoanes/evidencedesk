# Integração contínua

O workflow `.github/workflows/ci.yaml` prepara cinco grupos em Ubuntu 24.04 e um grupo de desenvolvimento Windows. O [CI do baseline `a3bbb77`](https://github.com/arthurjoanes/evidencedesk/actions/runs/35744912275) aprovou backend, frontend, navegador, histórico e as duas imagens. O grupo Windows e o checker de âncoras foram acrescentados depois: seus resultados locais estão em [verificação](../publication.md). Confira o SHA e a conclusão correspondente nas [execuções do workflow](https://github.com/arthurjoanes/evidencedesk/actions/workflows/ci.yaml).

## Verificações e falhas

| Job                     | Verificação e condição de falha                                                                                                                                                                                                                                                                                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `windows-development`   | Instalação nova com hashes em Python 3.11, consistência das dependências, testes de scripts, unitários backend e documentação. Protege o percurso Windows; não substitui PostgreSQL real no job Linux.                                                                                                                                                                                                                                |
| `secret-history`        | Gitleaks 8.30.1 baixado da distribuição oficial e conferido por SHA-256; histórico completo com saída redigida. Achados de segredo reprovam. Exceções são limitadas a hashes de relatório e uma URL interna comprovados como falsos positivos.                                                                                                                                                                                        |
| `backend-and-operation` | Dependências Python com hashes, Ruff com configuração explícita, Mypy, links/arquivos da documentação, helpers e pytest sem provedor pago. Banco principal do runner em 5546 e banco de integração/manutenção separado em 5547, ambos migrados. Configurações de observabilidade validadas pelas ferramentas e build da API.                                                                                                          |
| `frontend`              | Instalação npm pelo lock sem scripts de terceiros, assets locais, tipos, lint, formato, unitários e build. `npm audit --omit=dev --audit-level=high` falha diante de HIGH/CRITICAL ou erro da consulta.                                                                                                                                                                                                                               |
| `browser-journeys`      | Grupos `core` e `stories`, cada um em projeto, volumes e banco novos. Perfil `--e2e` com UI3107/API8107 e banco sem porta publicada; chave vazia e provedor desativado impostos pelo override. Seed sintético e `qa-imports` são preparados em cada grupo antes do worker. Playwright Chromium executa uma vez, sem retry automático. Casos opcionais sem configuração são explicitamente ignorados; nenhuma geração paga é admitida. |
| `image-vulnerabilities` | Cada imagem runtime é construída e exportada por identidade; Trivy fixado por digest analisa todas as severidades. O gate reprova qualquer HIGH/CRITICAL, incluindo vulnerabilidades ainda sem correção. Erro do scanner, relatório ausente/incompatível ou ausência de alvos inspecionados também reprovam.                                                                                                                          |

Os jobs têm tempo máximo e o token GitHub possui apenas `contents: read`. Actions estão fixadas por SHA; credenciais do checkout não são persistidas. Artifacts são conservados por sete dias e coletados também quando uma verificação falha. O encerramento dos projetos de teste roda com `always()`; seus volumes vivem no runner descartável.

## Evidências e dados sensíveis

Os artefatos de navegador contêm dados sintéticos e podem incluir traces de falha. Os de segurança registram a identidade da imagem e o JSON de vulnerabilidades. Trivy usa **`--scanners vuln`**; o job Gitleaks examina segredos separadamente e não publica conteúdo encontrado como artifact. `publish_vulnerability_report.py` publica somente campos permitidos de vulnerabilidades, excluindo configuração/ambiente da imagem, histórico e `Secrets/Match`. A saída intermediária `scan-private/` não entra no artifact.

`--exit-code 0` na etapa do scanner permite avaliar o relatório completo no gate seguinte; não transforma findings em aprovação. `scripts/check_vulnerability_report.py` devolve código 1 para HIGH/CRITICAL e 2 para entrada inválida. Nenhum `--ignore-unfixed` ou filtro de severidade remove findings do relatório. A base do scanner é consultada no momento da execução, portanto um artefato que passou anteriormente pode reprovar depois.

## Validação local e limites

Os testes do scanner cobrem alvo limpo, HIGH sem versão corrigida, formato incompleto, identidade incompatível e remoção de metadados sensíveis. Os helpers passam Ruff com a configuração do workflow. Actionlint 1.7.12 aprovou a configuração com o grupo Windows em 22/09; isso não substitui sua execução no GitHub. A [verificação para publicação](../publication.md) reúne os resultados atuais de backend, scripts e navegador.

Uma execução completa usa dois namespaces e bancos recém-preparados. O limite real é de **10 tentativas de login por e-mail em 15 minutos**, incluindo logins bem-sucedidos e a substituição de sessão. Não há reset do contador nem alteração dessa política para testes. Com a configuração padrão, `core` faz 10 logins de Ana, 2 de Bruno e 4 de Carla; `stories` faz 3 de Ana, 3 de Bruno e 1 de Carla. Não faça login manual adicional no banco de `core`, nem repita a suíte na mesma janela. Seeds e uploads de QA nunca devem ser apontados para dados de produção.

## Reproduzir os dois grupos localmente

Prepare as dependências de [desenvolvimento](../development.md) e mantenha as fontes iguais entre os grupos. Construa uma vez as imagens próprias desta rodada; ambos os projetos podem reutilizar essas mesmas imagens. Os tags abaixo pertencem ao ensaio e não substituem imagens de outro laboratório:

```powershell
$e2eRun = Get-Date -Format yyyyMMddHHmmss
$coreProject = 'pf-evidencedesk-e2e-core-' + $e2eRun
$env:ED_BACKEND_IMAGE = 'pf-evidencedesk-backend:e2e-' + $e2eRun
$env:ED_FRONTEND_IMAGE = 'pf-evidencedesk-frontend:e2e-' + $e2eRun
python scripts/ops.py --project $coreProject --e2e build
docker image inspect $env:ED_BACKEND_IMAGE $env:ED_FRONTEND_IMAGE --format '{{.Id}}'
Push-Location frontend
npm ci --ignore-scripts
npm run prepare:assets
npx playwright install chromium
Pop-Location
```

Execute o bloco seguinte primeiro com `$group = 'core'` e depois com `$group = 'stories'`, conservando os tags das imagens acima. Cada nome cria seu próprio banco e volumes. O perfil publica as mesmas portas de loopback 3107/8107; o `finally` encerra somente o projeto daquele grupo antes de liberar as portas para o próximo. O seed e `prepare_e2e.py` rodam em ambos os bancos, antes de iniciar API, worker e interface:

```powershell
$group = 'core' # Na segunda execução, use 'stories'.
$groupProject = 'pf-evidencedesk-e2e-' + $group + '-' + $e2eRun
$env:ED_E2E_BASE_URL = 'http://127.0.0.1:3107'
$env:ED_E2E_ARTIFACT_DIR = Join-Path $env:TEMP ('evidencedesk-e2e-' + $group + '-' + $e2eRun)
$env:ED_PAYMENT_STORY = '1'
try {
    python scripts/ops.py --project $groupProject --e2e db
    docker compose -p $groupProject -f infra/compose/compose.yaml -f infra/compose/e2e.yaml run --rm --no-deps migrate
    python scripts/ops.py --project $groupProject --e2e seed
    docker compose -p $groupProject -f infra/compose/compose.yaml -f infra/compose/e2e.yaml run --rm --no-deps -v "${PWD}/scripts:/ops:ro" seed python /ops/prepare_e2e.py
    python scripts/ops.py --project $groupProject --e2e start
    Push-Location frontend
    try {
        npm run "test:e2e:$group"
        if ($LASTEXITCODE -ne 0) { throw "O grupo $group falhou; confira seu relatório privado." }
    } finally {
        Pop-Location
    }
} finally {
    python scripts/ops.py --project $groupProject --e2e stop
}
```

Confira a seleção sem autenticar com `npm run test:e2e:core -- --list` e `npm run test:e2e:stories -- --list`, na pasta `frontend`. São 17 testes em `core` e quatro em `stories`, sem sobreposição. O comando bruto `npm run test:e2e` permanece disponível, mas os 21 testes executados rapidamente em um único banco ultrapassam o limite de Ana. `stories` exige `ED_PAYMENT_STORY=1`. Sem configuração própria, a leitura de geração existente e as três jornadas de restauração ficam puladas; registre essa cobertura não executada. Habilitar `existing-run` acrescenta um login de Ana e requer outro grupo isolado.

Os relatórios de cada grupo ficam no diretório privado indicado por `ED_E2E_ARTIFACT_DIR`, fora do Git; não publique cookies, traces ou logs brutos. `stop` preserva os volumes, o histórico de login e os dados para inspeção. Para repetir uma rodada, gere outro `$e2eRun`, prepare novos projetos e confira as imagens que serão reutilizadas. Não remova volumes de outros projetos nem redefina contadores para obter uma aprovação.

Os scans iniciais de 21/09/2026 reprovaram as imagens Debian. A revisão para publicação atualizou as bases e corrigiu os pacotes de runtime; os resultados históricos foram preservados. Consulte [a revisão com identidades das imagens](../publication-security.md). O CI remoto citado na abertura passou no baseline; sua aprovação não se transfere a commits posteriores. Não há waiver automática para findings sem correção. Alterações no provedor, carga real, Azure hospedado e avaliação humana de conclusões continuam fora deste CI. As jornadas com respostas controladas são identificadas no código e não substituem os testes de autorização e concorrência do backend.

Para repetir o ensaio offline com Trivy e base já disponíveis, a partir da raiz: `python scripts/scan_runtime_images.py --cache-db CAMINHO_PARA_DB --services api frontend --evidence-name NOME_NOVO`. A pasta precisa conter `metadata.json` e `trivy.db`, com base de até 72h. O comando não baixa imagem/base, não reinicia serviços, congela os IDs antes do scan e recusa sobrescrever uma pasta de evidências. Usa até 1 GiB de memória e uma CPU por scanner, uma imagem por vez. A escolha explícita do cache permite usar uma base existente sem alterar seu conteúdo; o comando verifica o hash antes/depois.

Referências oficiais: [Trivy para imagens](https://trivy.dev/docs/dev/guide/target/container_image/), [opções do comando image](https://trivy.dev/docs/dev/references/configuration/cli/trivy_image/) e [códigos de saída](https://trivy.dev/docs/dev/guide/configuration/others/).
