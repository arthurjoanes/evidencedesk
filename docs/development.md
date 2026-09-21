# Desenvolvimento e testes

A demonstração usa Docker e os comandos do [README](../README.md). Este guia prepara o ambiente de desenvolvimento e um PostgreSQL descartável. O banco da demonstração usa a porta 5546; os testes usam 5547 e volumes próprios.

## Preparar Python

Na raiz, em PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes -r backend/requirements-test.lock
$env:PYTHONPATH = (Join-Path (Get-Location).Path 'backend/src')
$env:ED_AI_PROVIDER = 'disabled'
```

Em Linux, use `.venv/bin/python` e `export PYTHONPATH="$PWD/backend/src"`. O [workflow](../.github/workflows/ci.yaml) contém a sequência Linux. `PYTHONPATH` evita depender de uma instalação editável vinculada a outra pasta.

## Backend e operação

```powershell
.venv/Scripts/python.exe -m ruff check backend/src backend/tests scripts --config backend/pyproject.toml
.venv/Scripts/python.exe -m ruff format --check backend/src backend/tests scripts --config backend/pyproject.toml
.venv/Scripts/python.exe -m mypy backend/src --config-file backend/pyproject.toml
.venv/Scripts/python.exe -m unittest discover -s scripts -p 'test_*.py'
python scripts/check_repository_docs.py
```

A suíte completa exige PostgreSQL real. Prepare o namespace de teste:

```powershell
docker compose -p pf-evidencedesk-tests -f infra/compose/compose.yaml -f infra/compose/integration.yaml up -d --wait db
$env:ED_TEST_DATABASE_URL = 'postgresql+psycopg://ed_app:ed_app_local_demo@127.0.0.1:5547/evidencedesk'
$env:ED_TEST_ADMIN_DATABASE_URL = 'postgresql+psycopg://postgres:ed_admin_local_demo@127.0.0.1:5547/evidencedesk'
$env:ED_MAINTENANCE_TEST_DATABASE_URL = $env:ED_TEST_DATABASE_URL
$env:ED_MAINTENANCE_TEST_OWNER_URL = 'postgresql+psycopg://ed_owner:ed_owner_local_demo@127.0.0.1:5547/evidencedesk'
$env:ED_MIGRATION_DATABASE_URL = $env:ED_MAINTENANCE_TEST_OWNER_URL
Push-Location backend
../.venv/Scripts/python.exe -m alembic upgrade head
Pop-Location
.venv/Scripts/python.exe -m pytest backend/tests -m 'not azure' -q
```

As integrações recusam a porta da demonstração e usam organizações temporárias. Sem as variáveis explícitas, parte da suíte é ignorada: isso não comprova as garantias do banco. Ao terminar:

```powershell
docker compose -p pf-evidencedesk-tests -f infra/compose/compose.yaml -f infra/compose/integration.yaml stop
```

O teste de links simbólicos pode ser ignorado no Windows se a conta não tiver essa permissão. O runner Linux executa esse cenário.

## Frontend

Requer Node 24+. A partir de `frontend/`:

```powershell
npm ci --ignore-scripts
npm run prepare:assets
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
```

Os testes de navegador usam a aplicação compilada, API e worker. O perfil E2E fixa o provedor desativado e a chave vazia. Execute da raiz:

```powershell
python scripts/ops.py --project pf-evidencedesk-e2e-dev --e2e build
python scripts/ops.py --project pf-evidencedesk-e2e-dev --e2e start
python scripts/ops.py --project pf-evidencedesk-e2e-dev --e2e seed
$testScripts = (Join-Path (Get-Location).Path 'scripts')
docker compose -p pf-evidencedesk-e2e-dev -f infra/compose/compose.yaml -f infra/compose/e2e.yaml run --rm --no-deps -v "${testScripts}:/ops:ro" seed python /ops/prepare_e2e.py
$env:ED_E2E_BASE_URL = 'http://127.0.0.1:3107'
Push-Location frontend
npx playwright install chromium
npm run test:e2e
Pop-Location
python scripts/ops.py --project pf-evidencedesk-e2e-dev --e2e stop
```

Use uma instância nova para cada rodada completa; os limites de login continuam ativos. Apenas um perfil E2E pode ocupar 3107/8107 por vez. A leitura de uma geração Azure histórica é opcional e exige IDs já existentes; a suíte padrão não gera uma resposta paga.

## Segurança e evidências

O [CI](runbooks/ci.md) também examina histórico Git e imagens runtime. Os relatórios conservam imagem, versão do scanner e data da base. Uma alteração de fonte exige novo build; a aprovação de uma imagem anterior não aprova outra.

`check_repository_docs.py` verifica links locais contra arquivos que entram no Git. Capturas ignoradas, caminhos privados ou arquivos ausentes reprovam o check, mesmo que funcionem na máquina do autor. O comando não consulta links externos.

Resultados: [verificação para publicação](publication.md) e [revisão de segurança](publication-security.md).
