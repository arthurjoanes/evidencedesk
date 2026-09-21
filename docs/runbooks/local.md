# Operação local

Pré-requisitos: Docker Compose 2.24.4+ (suporte a `!reset`), Python 3.11+ e os lockfiles versionados. O projeto usa Linux containers. Execute os comandos na raiz do repositório; `scripts/ops.ps1` encaminha argumentos e exit code para o mesmo CLI Python.

```powershell
python scripts/ops.py config
python scripts/ops.py build
python scripts/ops.py start
python scripts/ops.py seed
python scripts/ops.py status
```

Builds não mudam a imagem de um container já em execução; `start` recria quando necessário. Migrações terminam antes de API/workers iniciarem. Um seed é explícito e repetível. Os defaults são credenciais públicas de demonstração local, nunca produção. UI: http://127.0.0.1:3106; API: http://127.0.0.1:8106; banco de depuração: 127.0.0.1:5546.

`python scripts/ops.py stop` para os containers em execução com o label exato deste projeto, incluindo observabilidade/modelos opcionais ou serviços de uma definição Compose anterior, e preserva volumes. O CLI não oferece prune nem remoção global. `--project` aceita apenas o namespace `pf-evidencedesk` e seus sufixos. Outro projeto exige portas próprias no env file; um nome diferente não resolve colisão de porta sozinho.

## Configuração e segredos

Use `infra/compose/runtime.env.example` como referência. Um arquivo com credencial real deve ficar fora do repositório e do OneDrive, com acesso restrito à conta local. Passe seu caminho antes da ação:

```powershell
python scripts/ops.py --env-file C:\caminho-protegido\evidencedesk.env start
```

A validação usa `config --quiet`; nunca cole `docker compose config`, `docker inspect` completo ou um dump de ambiente em evidência. O processo Docker recebe as credenciais necessárias e administradores locais conseguem inspecioná-las; isto não equivale ao Managed Identity do perfil Azure futuro.

As senhas de banco interpoladas no Compose precisam ser URL-safe (letras, números, `_` e `-`). Alterar o env file depois que o volume foi inicializado não altera as senhas dos roles. Rotação exige ALTER ROLE deliberado e atualização coordenada da aplicação; não apague um volume para resolver senha divergente.

Sem `AZURE_OPENAI_API_KEY`, a aplicação mantém a jornada manual e deve informar geração indisponível. Não há LLM local nem provisionamento Azure automático. Para desativação explícita, use `ED_AI_PROVIDER=disabled`. Um build nunca chama inferência.

No Windows, `pwsh -NoProfile -File scripts/azure_runtime.ps1 -Action configure` recebe a chave de forma oculta e guarda somente uma representação protegida por DPAPI em `%LOCALAPPDATA%/EvidenceDesk`, fora do Git e do OneDrive. Depois de um rebuild, use `-Action start` para recriar API/worker preservando credencial e OTLP. O helper fixa o projeto `pf-evidencedesk` e aguarda readiness. `ops.py start` recusa uma configuração que apagaria a chave de um container existente; o diagnóstico consulta apenas presença, sem retornar a credencial do Docker. Nenhum desses comandos provisiona infraestrutura ou chama o modelo.

## Navegador em ambiente isolado

Use `--project pf-evidencedesk-e2e-<id> --e2e` antes da ação do CLI. O override publica somente UI3107/API8107 em loopback, não publica o banco e usa volumes próprios. Ele fixa provedor desativado, chave vazia, origins3107 e `ED_E2E_MODE=true`, inclusive quando o shell contém uma chave. Não execute duas instâncias desse perfil nas mesmas portas. A combinação com observabilidade compartilhada é recusada.

Para preparar, execute `db`, a migração one-off usando os dois arquivos Compose, `seed`, `scripts/prepare_e2e.py` pelo serviço seed com mount readonly de scripts e então `start`. A sequência completa está no job `browser-journeys` do CI. O helper de fixtures recusa ausência de E2E explícito, provedor habilitado ou chave presente antes de acessar o banco. A coleção `qa-imports` é separada; nenhuma política da instância principal é redefinida para facilitar testes.

## Falha no start

Leia `python scripts/ops.py logs migrate` se a API não iniciou. Não reinicie migração simultaneamente por fora do Compose. Confirme a role owner, versão de schema e espaço livre. `logs api` e `logs worker` limitam a saída; não transportam deliberadamente conteúdo de documentos/prompts. Nunca conceda SUPERUSER/BYPASSRLS à conta da aplicação para contornar erro de permissão.

Readiness depende das condições mínimas para servir; liveness apenas da vida do processo. Um container `running` sem readiness não é jornada validada. Docker restart policy reinicia um processo que morreu; não corrige automaticamente um serviço apenas marcado unhealthy.

## Recursos

Consulte [environment.md](../environment.md). Não inicie observabilidade, treino e build frontend ao mesmo tempo sem observar RAM livre. `docker stats` mede containers; a RAM do Windows e a do daemon WSL são visões diferentes. Caches/objetos/DB ficam em volumes, fora das fontes sincronizadas.

## Verificação

```powershell
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/check_infra.py
```

`check_infra.py` executa validadores das versões fixadas, além de testes de regras. Não inicia a stack nem demonstra funcionamento da aplicação. O registro preserva exit code por check. O workflow em `.github/workflows/ci.yaml` executa testes sem credencial Azure; presença do YAML não comprova que o GitHub Actions já executou.
