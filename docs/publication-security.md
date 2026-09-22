# Segurança das imagens para publicação

A revisão do perfil opcional de ML em 21/09/2026 identificou CVE-2026-69112 no Accelerate. A [correção local do loader](ml-checkpoint-security.md) inclui hashes e 15 regressões; é um ensaio separado do gate de API/frontend abaixo. O pacote mantém sua versão original nos metadados, portanto scanners por versão continuam identificando o advisory.

Em **21/09/2026**, o gate das imagens finais locais Linux/amd64 de API e frontend passou com **zero vulnerabilidades reportadas em todas as severidades**. O [resumo verificável](evidence/publication-security-release/summary.json) registra as identidades das imagens, a versão do scanner e o hash da base. Este ensaio inclui as últimas validações de formulário, a configuração Azure portátil e a mensagem final de disponibilidade do gerador; substitui, para a revisão atual, o [scan intermediário](evidence/publication-security/summary.json). O resultado se aplica às imagens inspecionadas e à cobertura dessa base; não é uma certificação de ausência de vulnerabilidades.

| Imagem | Pacotes de sistema inspecionados | Pacotes de aplicação inspecionados | HIGH / CRITICAL |
| --- | ---: | ---: | ---: |
| API | 38 | 63 Python | 0 / 0 |
| Frontend | 18 | 20 Node.js | 0 / 0 |

Os inventários e resultados estão nos relatórios [API](evidence/publication-security-release/api-vulnerabilities.json) e [frontend](evidence/publication-security-release/frontend-vulnerabilities.json). As imagens opcionais de ML, PostgreSQL e observabilidade estão fora deste ensaio.

## Correções aplicadas

- As bases Debian Bookworm foram substituídas pelas variantes oficiais Alpine 3.24, mantendo Python 3.12.14 e Node.js 24.19.0. As bases estão fixadas por digest nos Dockerfiles. Bibliotecas e utilitários Debian que não eram necessários ao serviço deixaram de integrar o runtime.
- O backend instala somente wheels compatíveis, com o lock e todos os hashes existentes. Isso impede uma compilação nativa implícita ou a mistura de binários glibc com musl. A instalação dos pacotes `cryptography`, `psycopg-binary`, `argon2`, `pydantic-core`, `uvloop` e `httptools` passou; seus imports foram verificados dentro da imagem.
- `pip` e `ensurepip` foram removidos do runtime Python. O frontend continua sem npm, Corepack e Yarn em execução. As distribuições da aplicação e a base de pacotes do sistema são preservadas para inspeção; nenhum metadado de pacote foi apagado para esconder uma biblioteca mantida.
- A base Node ainda continha OpenSSL 3.5.7. `libcrypto3` e `libssl3` foram atualizados para **3.5.8-r0**, em build e runtime. O build falha se essas versões explícitas deixarem de estar disponíveis. O [ensaio da candidata](evidence/publication-security-candidate/summary.json) preserva os dois HIGH anteriores à correção e os achados de pip anteriores à remoção.
- Trivy foi atualizado para **0.74.0**, fixado por digest tanto no comando local como no CI. O CI usa explicitamente `--ignorefile /dev/null`; não há `--ignore-unfixed`, filtro de severidade nem exceções CVE. O gate continua reprovando todo HIGH/CRITICAL que o scanner reportar.

## Evidência e limites

O scanner inspecionou cada arquivo exportado por ID imutável, sem acesso à rede, com a base de 21/09/2026 às 07:13 UTC. Seu SHA-256 foi comparado antes e depois. O relatório só é publicado se a identidade da configuração coincidir com a imagem exportada e se houver alvos de sistema e linguagem. A publicação retém apenas inventário de nomes/versões e campos permitidos de vulnerabilidades; ambiente, histórico e resultados de scanner de segredos ficam de fora.

A [documentação oficial do Trivy para Alpine](https://trivy.dev/docs/latest/coverage/os/alpine/) informa cobertura limitada de vulnerabilidades sem correção no feed dessa distribuição. Por isso os números Debian e Alpine não constituem uma comparação de cobertura idêntica. O relatório vazio significa que não houve achados na cobertura consultada; novos advisories ou bases podem mudar o resultado. O scanner também emitiu aviso de ausência de Alpine 3.24 em sua tabela interna de fim de suporte. A [tabela oficial Alpine](https://alpinelinux.org/releases/) confirma suporte da linha 3.24 e fim previsto para o repositório principal em 01/06/2028; a detecção de pacotes e a consulta de CVEs do repositório 3.24 foram executadas.

Os builds passaram e os imports Python foram executados como UID 10001, com filesystem somente leitura e sem capabilities. Os 75 arquivos Python embarcados foram comparados byte a byte com a fonte final; ambas as mensagens das validações finais de formulário foram encontradas nos chunks JavaScript compilados. A [verificação do runtime](evidence/publication-security-release/runtime-validation.json) registra esses controles nas mesmas identidades do scan. Os nove testes do gate/publicação passaram, inclusive HIGH sem correção, relatório incompleto, identidade incompatível, configuração OCI com campos `rootfs` e `config`, conteúdo adulterado e remoção de metadados sensíveis. Ruff passou nos helpers alterados.

O CI também possui um job separado de histórico de segredos: checkout completo, Gitleaks 8.30.1 CLI, checksum SHA-256 fixo confirmado no release oficial, `git --redact --log-opts=--all` e saída sem artifact de Matches. A configuração mantém as regras padrão e exceções locais estritas para hashes de relatório e URL interna comprovados. Os quatro pins de Actions foram conferidos nos repositórios oficiais; Actionlint 1.7.12 aprovou os cinco jobs, com ShellCheck/Pyflakes externos desativados. A [verificação das ferramentas](evidence/publication-security-release/workflow-validation.json) registra versões e integridade. Esses resultados locais não substituem a execução remota do GitHub Actions, a validação funcional completa nem a avaliação humana da IA.

## Repetir

Na raiz do projeto, com Docker e Python disponíveis:

```console
docker build -t pf-evidencedesk-backend:publication-alpine backend
docker build -t pf-evidencedesk-frontend:publication-alpine frontend
docker pull aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
python scripts/scan_runtime_images.py --cache-db CAMINHO_PARA_DB --image-tag publication-alpine --evidence-name publication-security-nova
```

O cache deve conter `metadata.json` e `trivy.db`, esquema 2 e idade máxima de 72 horas. O comando exige pasta de evidências nova e não altera tags, serviços nem volumes existentes. O [CI](runbooks/ci.md) baixa a base atual e executa o mesmo gate em cada imagem construída. Ao atualizar bases, pacotes ou scanner, repetir build, testes de integração/navegador e scan; preservar o relatório mesmo quando o gate reprovar.

Referências de compatibilidade: [variantes oficiais Node e musl](https://github.com/nodejs/docker-node/blob/main/README.md#nodealpine), [imagens oficiais Python](https://github.com/docker-library/official-images/blob/master/library/python) e [release Trivy 0.74.0](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0).
