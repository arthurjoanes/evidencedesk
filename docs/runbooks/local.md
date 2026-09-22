# Operação local

Contrato de endpoint consultado em **22/09/2026**: a [documentação Microsoft](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints) confirma a rota `/openai/v1/`, os dois formatos de host de recurso e o nome do deployment em `model`. A disponibilidade de Responses depende do deployment; não há chamada paga nem novo teste Azure nesta revisão.

Pré-requisitos: Docker Compose 2.24.4+ (suporte a `!override` nos overlays), Python 3.11+ e os lockfiles versionados. Fontes: [regra oficial de merge do Compose](https://docs.docker.com/reference/compose-file/merge/#replace-value), [overlay de integração](../../infra/compose/integration.yaml) e [CLI](../../scripts/ops.py), conferidas em **22/09/2026**. O projeto usa Linux containers. Execute os comandos na raiz do repositório; `scripts/ops.ps1` encaminha argumentos e exit code para o mesmo CLI Python.

```powershell
python scripts/ops.py config
python scripts/ops.py build
python scripts/ops.py start
python scripts/ops.py seed
python scripts/ops.py status
```

Builds não mudam a imagem de um container já em execução; `start` recria quando necessário. Migrações terminam antes de API/workers iniciarem. O seed é explícito e repetível: em um clone novo, gera primeiro os seis pacotes sintéticos em `datasets/generated`. Se encontrar uma pasta parcial sem índice, interrompe com instrução de recuperação em vez de sobrescrever seus arquivos. Os defaults são credenciais públicas de demonstração local, nunca produção. UI: http://127.0.0.1:3106; API: http://127.0.0.1:8106; banco de depuração: 127.0.0.1:5546.

`python scripts/ops.py stop` para os containers em execução com o label exato deste projeto, incluindo observabilidade/modelos opcionais ou serviços de uma definição Compose anterior, e preserva volumes. O CLI não oferece prune nem remoção global. `--project` aceita apenas o namespace `pf-evidencedesk` e seus sufixos. Outro projeto exige portas próprias no env file; um nome diferente não resolve colisão de porta sozinho.

Fontes desta seção, conferidas em **22/09/2026**: [ops.py](../../scripts/ops.py) · [config.py](../../backend/src/evidencedesk/config.py) · [compose.yaml](../../infra/compose/compose.yaml).

## Configuração e segredos

Use `infra/compose/runtime.env.example` como referência. Um arquivo com credencial real deve ficar fora do repositório e do OneDrive, com acesso restrito à conta local. Passe seu caminho antes da ação:

```powershell
python scripts/ops.py --env-file C:\caminho-protegido\evidencedesk.env start
```

A validação usa `config --quiet`; nunca cole `docker compose config`, `docker inspect` completo ou um dump de ambiente em evidência. O processo Docker recebe as credenciais necessárias e administradores locais conseguem inspecioná-las; isto não equivale ao Managed Identity do perfil Azure futuro.

As senhas de banco interpoladas no Compose precisam ser URL-safe (letras, números, `_` e `-`). Alterar o env file depois que o volume foi inicializado não altera as senhas dos roles. Rotação exige ALTER ROLE deliberado e atualização coordenada da aplicação; não apague um volume para resolver senha divergente.

Sem configuração Azure completa, a aplicação mantém a jornada manual e informa geração indisponível. Não há endpoint ou deployment pessoal como default. Para desativação explícita, use `ED_AI_PROVIDER=disabled`. Um build nunca chama inferência.

### Azure opcional com recurso próprio

Configure seu endpoint de recurso e o nome de um deployment compatível com Responses e saída estruturada. A API v1 aceita `https://<recurso>.openai.azure.com/openai/v1/` e `https://<recurso>.services.ai.azure.com/openai/v1/`; o campo `model` recebe o nome do deployment no seu recurso. [Documentação Microsoft](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints).

No arquivo protegido de runtime, preencha os quatro valores abaixo; mantenha as demais configurações da sua instalação:

```dotenv
ED_AI_PROVIDER=azure_openai
AZURE_OPENAI_BASE_URL=https://seu-recurso.openai.azure.com/openai/v1/
AZURE_OPENAI_DEPLOYMENT=seu-deployment
ED_AZURE_OPENAI_ALLOWED_HOSTS=seu-recurso.openai.azure.com
AZURE_OPENAI_API_KEY=<chave-do-seu-recurso>
```

`ED_AZURE_OPENAI_ALLOWED_HOSTS` é configuração confiável do operador: uma lista de hosts exatos separados por vírgulas. O padrão é vazio. O runtime exige HTTPS, porta 443 e a rota `/openai/v1/` nos dois domínios Azure acima; rejeita IPs, outros domínios, credenciais na URL, curingas, queries e fragmentos. Remover um host da lista também bloqueia novas chamadas de execuções já enfileiradas. Não use um endpoint de projeto `/api/projects/...`. Este perfil não inclui endpoints de clouds soberanas ou proxies personalizados.

No Windows, o helper evita uma chave em texto claro no arquivo de runtime:

```powershell
pwsh -NoProfile -File scripts/azure_runtime.ps1 -Action configure -Endpoint "https://seu-recurso.openai.azure.com/openai/v1/" -Deployment "seu-deployment"
pwsh -NoProfile -File scripts/azure_runtime.ps1 -Action start
```

`configure` pede a chave com entrada oculta e grava `%LOCALAPPDATA%/EvidenceDesk/azure-openai.runtime.json`, fora do Git e do OneDrive. Endpoint, deployment e host autorizado são metadados não secretos; a chave fica cifrada por DPAPI para a conta Windows. A configuração inteira é substituída atomicamente depois da validação; um erro preserva a anterior. O arquivo legado `azure-openai.dpapi` não é sobrescrito nem migrado implicitamente: execute novamente `configure` com endpoint, deployment e chave. A ação não faz uma chamada de verificação paga.

Se a instalação usa um arquivo de runtime próprio, passe o mesmo arquivo no `start`: `pwsh -NoProfile -File scripts/azure_runtime.ps1 -Action start -EnvFile C:\caminho-protegido\evidencedesk.env`. Observabilidade é opcional: acrescente `-Observability` somente para iniciar esse perfil. Essas duas opções são informadas em cada inicialização. O helper encaminha a operação para `ops.py start`, injeta a configuração Azure apenas no processo e restaura as variáveis anteriores ao terminar, inclusive em falha. As configurações salvas de endpoint/deployment/chave têm precedência sobre os respectivos valores do env file.

`ops.py start` recusa uma configuração que apagaria a chave de um container existente; o diagnóstico consulta apenas presença, sem retornar a credencial do Docker. Iniciar serviços não provisiona recursos Azure nem envia uma investigação de teste; workers podem processar trabalhos já enfileirados.

Fontes desta seção, conferidas em **22/09/2026**: [ops.py](../../scripts/ops.py) · [config.py](../../backend/src/evidencedesk/config.py) · [compose.yaml](../../infra/compose/compose.yaml).

## Navegador em ambiente isolado

Use `--project pf-evidencedesk-e2e-<id> --e2e` antes da ação do CLI. O override publica somente UI3107/API8107 em loopback, não publica o banco e usa volumes próprios. Ele fixa provedor desativado, chave vazia, origins3107 e `ED_E2E_MODE=true`, inclusive quando o shell contém uma chave. Não execute duas instâncias desse perfil nas mesmas portas. A combinação com observabilidade compartilhada é recusada.

Para preparar, execute `db`, a migração one-off usando os dois arquivos Compose, `seed`, `scripts/prepare_e2e.py` pelo serviço seed com mount readonly de scripts e então `start`. A sequência completa está no job `browser-journeys` do CI. O helper de fixtures recusa ausência de E2E explícito, provedor habilitado ou chave presente antes de acessar o banco. A coleção `qa-imports` é separada; nenhuma política da instância principal é redefinida para facilitar testes.

Fontes desta seção, conferidas em **22/09/2026**: [ops.py](../../scripts/ops.py) · [config.py](../../backend/src/evidencedesk/config.py) · [compose.yaml](../../infra/compose/compose.yaml).

## Falha no start

Leia `python scripts/ops.py logs migrate` se a API não iniciou. Não reinicie migração simultaneamente por fora do Compose. Confirme a role owner, versão de schema e espaço livre. `logs api` e `logs worker` limitam a saída; não transportam deliberadamente conteúdo de documentos/prompts. Nunca conceda SUPERUSER/BYPASSRLS à conta da aplicação para contornar erro de permissão.

Readiness depende das condições mínimas para servir; liveness apenas da vida do processo. Um container `running` sem readiness não é jornada validada. Docker restart policy reinicia um processo que morreu; não corrige automaticamente um serviço apenas marcado unhealthy.

Fontes desta seção, conferidas em **22/09/2026**: [ops.py](../../scripts/ops.py) · [config.py](../../backend/src/evidencedesk/config.py) · [compose.yaml](../../infra/compose/compose.yaml).

## Recursos

Consulte [environment.md](../environment.md). Não inicie observabilidade, treino e build frontend ao mesmo tempo sem observar RAM livre. `docker stats` mede containers; a RAM do Windows e a do daemon WSL são visões diferentes. Caches/objetos/DB ficam em volumes, fora das fontes sincronizadas.

Fontes desta seção, conferidas em **22/09/2026**: [ops.py](../../scripts/ops.py) · [config.py](../../backend/src/evidencedesk/config.py) · [compose.yaml](../../infra/compose/compose.yaml).

## Verificação

Prepare antes o ambiente do [guia de desenvolvimento](../development.md); os testes de operação usam dependências do backend. O CLI `ops.py` e o gerador sintético usam somente a biblioteca padrão.

```powershell
.venv/Scripts/python.exe -m unittest discover -s scripts -p 'test_*.py'
python scripts/check_infra.py
```

`check_infra.py` executa validadores das versões fixadas, além de testes de regras. Não inicia a stack nem demonstra funcionamento da aplicação. O registro preserva exit code por check. O workflow em `.github/workflows/ci.yaml` executa testes sem credencial Azure; presença do YAML não comprova que o GitHub Actions já executou.

Fontes desta seção, conferidas em **22/09/2026**: [ops.py](../../scripts/ops.py) · [config.py](../../backend/src/evidencedesk/config.py) · [compose.yaml](../../infra/compose/compose.yaml).
