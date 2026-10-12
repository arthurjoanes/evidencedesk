# Revisão semântica local e casos adversariais

O laboratório prepara rodadas sobre os 60 casos dev do [pacote humano](../../evals/human-review/package.json). Revisores trabalham em um HTML local, e a CLI valida os arquivos exportados antes de importar ou adjudicar. O resultado não aprova dossiês da aplicação e não promove o reranker.

Use Python 3.11+ e as dependências já fixadas no projeto. O fluxo de revisão não exige Node, Docker, Azure, pesos ou servidor HTTP. Node e Chromium são necessários somente para os testes automatizados do navegador.

```powershell
python -m pip install --require-hashes -r backend/requirements-test.lock -r scripts/requirements-docs.lock
python -m evals.workbench --help
python -m evals.workbench schema --kind round-spec
```

## Preparar uma rodada sem inventar respostas

Escolha uma pasta privada fora de qualquer checkout Git. Use uma pasta nova para cada versão avaliada. O comando de preparação verifica o índice dev, o hash do arquivo de casos e cada fonte dev, sem abrir o reservado. Ele recusa IDs desconhecidos, duplicatas, caminhos que escapem da raiz permitida, arquivos grandes e JSON inválido.

Copie [round.template.json](../../evals/human-review/round.template.json) para essa pasta. Preencha `round_id`, `planned_case_ids`, `system_codes` e os campos de release conhecidos. `commit` precisa identificar a fonte avaliada; se houver alterações locais, preserve também o diff completo e os hashes ou use uma imagem/snapshot construído da fonte congelada. O commit sozinho não identifica arquivos modificados. Política de chunks, parser, perfil de retrieval e revisões de modelos que não foram verificadas continuam `null`.

Exemplo de preparação de um caso planejado para dois sistemas, ainda sem geração:

```powershell
$private = Join-Path $env:TEMP 'evidencedesk-review-minha-rodada'
New-Item -ItemType Directory -Path $private
$spec = Get-Content evals/human-review/round.template.json -Raw | ConvertFrom-Json
$spec.round_id = 'review-dev-minha-rodada'
$spec.release.id = 'candidate-minha-rodada'
$spec.release.commit = (git rev-parse HEAD).Trim()
$spec.release.chunk_policy = 'utf8-bytes-352-v2'
$spec.release.parser_rules_version = 'text-pdf-v2'
$spec.release.retrieval_profile = 'lexical'
$spec.planned_case_ids = @('evaluation-dev-000')
$spec.system_codes = @('A', 'B')
$spec | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8NoBOM "$private/round-spec.json"
'{"schema_version":1,"responses":[]}' | Set-Content -Encoding utf8NoBOM "$private/responses.json"
python -m evals.workbench prepare --round-spec "$private/round-spec.json" --responses "$private/responses.json" --output "$private/round"
python -m evals.workbench ui --output "$private/workbench.html"
python -m evals.workbench bundle --round "$private/round" --reviewer revisor-01 --output "$private/revisor-01.json"
python -m evals.workbench report --round "$private/round" --output "$private/report.html"
```

Esses comandos usam PowerShell 7. Em Windows PowerShell 5, grave JSON como UTF-8 sem BOM por uma ferramenta equivalente. Abra `workbench.html` no navegador e importe `revisor-01.json`. Os dois sistemas permanecem `not_run`, e o gate é inconclusivo. A preparação não chama um gerador.

Para revisar uma resposta existente, o arquivo `responses.json` deve conter seu texto exato, estado e todas as alegações identificadas. Inclua fontes e localizadores realmente presentes no corpus congelado, quando houver citações. Uma alegação sem fonte conserva `references: []`. Falhas precisam de `failure_reason`; omitir uma execução mantém o par caso/sistema como `not_run`.

```json
{
  "schema_version": 1,
  "responses": [
    {
      "case_id": "evaluation-dev-000",
      "system_code": "A",
      "state": "answered",
      "answer": "Texto exato da resposta avaliada.",
      "claims": [
        {
          "claim_id": "claim-1",
          "exact_claim": "Texto exato da alegação avaliada.",
          "references": []
        }
      ]
    }
  ]
}
```

O exemplo descreve o formato, sem simular um resultado humano. Não transforme texto demonstrativo em evidência semântica. O bundle conserva `round_id`, caso/incidente, sistema codificado, IDs das alegações, hash da resposta, fontes e seus hashes, localizadores, contexto temporal, manifesto, release e ordem de apresentação. O corpus informado na release é conferido ou preenchido a partir das fontes verificadas.

`schema --kind` também aceita `responses`, `bundle`, `annotations` e `adjudication`. Use `--output` em uma pasta privada para salvar o JSON Schema. As revisões e os campos desconhecidos são recusados pelos contratos; o limite de leitura/publicação é 16 MiB, com até 1 MiB por fonte dev. Divida uma rodada grande em planejamentos menores antes de exceder o limite.

## Revisar e importar

Gere um bundle separado para cada revisor. Entregue somente esse arquivo e o HTML. `round.json` e o relatório pertencem à coordenação/adjudicação e contêm referências de avaliação; não são material cego para o revisor nem contexto do gerador.

O navegador mostra alegação e fonte lado a lado em telas amplas; no móvel, a fonte precede o julgamento. A fila pode ser recolhida para concentrar a leitura no caso. Nenhum rótulo vem pré-selecionado. Para `supported`, escolha fonte e localizador válidos e registre o motivo. Os demais rótulos são `contradicted`, `insufficient` e `irrelevant`. Campos não avaliados continuam `null`. Informe assistência recebida, tempo e identidade declarada ao submeter. Essa identidade em arquivo não oferece autenticação institucional.

Filtrar ou trocar de caso preserva o rascunho em memória. Exporte-o para continuar depois; fechar ou substituir material com alterações pendentes exige aviso de descarte. O HTML não envia conteúdo pela rede e não usa `localStorage`. Um JSON baixado só entra na rodada depois da validação autoritativa:

```powershell
python -m evals.workbench validate --round "$private/round" --annotations "$private/anotacoes-revisor-01.json"
python -m evals.workbench import --round "$private/round" --annotations "$private/anotacoes-revisor-01.json"
python -m evals.workbench bundle --round "$private/round" --reviewer revisor-02 --output "$private/revisor-02.json"
python -m evals.workbench compare --round "$private/round"
```

Dois julgamentos submetidos são obrigatórios por resposta. Um revisor não recebe os rótulos do outro antes de sua própria submissão. `compare` fornece os julgamentos à coordenação somente após essas duas submissões. A importação preserva versões e exige a base atual. Repetir o mesmo arquivo é idempotente; uma base concorrente, resposta alterada ou release diferente gera conflito. Uma submissão importada é imutável. Para alterar resposta/corpus/release, prepare outra rodada.

## Adjudicar e ler o relatório

O adjudicador precisa ser distinto dos dois revisores. Mesmo quando concordam, a decisão final exige registro explícito; divergências nunca viram maioria automática ou julgamento por modelo.

```powershell
python -m evals.workbench adjudication-template --round "$private/round" --response evaluation-dev-000--A --adjudicator adjudicador-01 --output "$private/decisao.json"
# Preencha decisão, motivos, tempo, assistência e avaliação final no arquivo privado.
python -m evals.workbench adjudicate --round "$private/round" --decision "$private/decisao.json"
python -m evals.workbench report --round "$private/round" --output "$private/report.html"
```

O template da decisão permanece inválido até ser preenchido. A importação confere os hashes dos dois julgamentos e as divergências atuais, além de resposta, fontes e release. Rascunhos, submissões e adjudicações permanecem separados. O estado da rodada distingue `prepared`, `in_review`, `with_disagreements`, `adjudicated` e `completed`; conclusão do fluxo não equivale a aprovação do gate.

Cada leitura da rodada confere as fontes e os dados dos casos contra os bytes dev verificados, além dos inputs originais congelados. Hashes detectam incompatibilidade e vinculam versões; não são assinatura nem autenticação de quem escreveu o arquivo. Proteja a pasta privada da rodada e preserve os arquivos iniciais de avaliação.

Após as duas submissões, a coordenação pode fornecer ao adjudicador as referências privadas em `round.json`. O adjudicador registra quais fatos esperados foram cobertos; a comparação usa os fatos identificados nesse registro, sem um avaliador semântico automático. Preserve também omissões, contraevidência e limites temporais em vez de preencher dimensões que não foram examinadas.

O relatório apresenta casos, categorias e sistemas separados. Somente adjudicação completa de origem humana declarada produz suporte booleano: `supported` vira verdadeiro; outros rótulos completos viram falso; ausência permanece não avaliada. Dois revisores da mesma resposta não duplicam o caso. Falhas e não executados permanecem nos denominadores.

Os [limiares existentes](../../evals/README.md) continuam válidos: mínimo de 30 respostas adjudicadas de 15 incidentes independentes, cobertura das categorias exigidas e demais gates. Poucos casos, campos não avaliados e julgamentos `simulated_test` deixam o gate humano inconclusivo. Não há julgamentos humanos produzidos por esta entrega.

## Executar contratos adversariais

As fixtures de [adversarial_cases.json](../../evals/adversarial_cases.json) são públicas, dev e sintéticas. Ataques alteram texto, título e metadados de fontes, incluindo falsa instrução de sistema, delimitadores, pedido de vazamento com canário fictício, procedimento antigo, contraevidência omitida, causalidade inventada, citação sem suporte e números divergentes.

O executor usa o gerador e as fronteiras existentes com `httpx2.MockTransport`, já disponível no lock do runtime. As saídas tipadas e recusas verificam o contrato; hooks de persistência/orçamento simulados ficam identificados no resultado. Não há acesso a URL arbitrária, modelo real, ferramenta nova ou promoção do candidato. O comportamento semântico real permanece `not_run`, e a revisão humana permanece inconclusiva.

Prepare payloads para uma futura execução real ou execute o transporte simulado com estes comandos. Guarde os outputs na pasta privada da execução. Mudanças na resposta, corpus, release ou fronteiras executadas invalidam reutilização de resultados/anotações anteriores.

```powershell
$env:PYTHONPATH = 'backend/src'
python -m evals.adversarial prepare --output "$private/adversarial-prepared.json"
python -m evals.adversarial run --output "$private/adversarial-contracts.json"
```

## Verificar e preservar evidência

Congele o candidato e pause edições antes dos gates e capturas. Registre HEAD, diff completo, hashes de arquivos novos/modificados, locks, schemas e assets. Confira os hashes novamente depois da execução; uma mudança exige repetir a evidência afetada. Capturas do workbench usam somente fixtures sintéticas identificadas.

```powershell
python -m pytest evals/test_metrics.py evals/test_workbench.py evals/test_adversarial.py
python scripts/check_repository_docs.py
cd frontend
npm ci --ignore-scripts
npm run prepare:assets
npx playwright install chromium
$env:ED_WORKBENCH_ARTIFACT_DIR = "$private/browser"
$env:ED_WORKBENCH_CAPTURE = '1'
node ../evals/workbench.browser.mjs
```

Para regressões de produção, siga o [CI](../../.github/workflows/ci.yaml) com PostgreSQL descartável e schema até `0008`. Ausência de `ED_TEST_DATABASE_URL` e `ED_TEST_ADMIN_DATABASE_URL` produz skips; isso não verifica RLS ou revisão de dossiês. O HTML funciona sem esse ambiente. Nunca reutilize o banco de demonstração.

Em Docker, inventarie containers, redes, rotas e portas sem imprimir Env. Use projeto `pf-evidencedesk-e2e-evolucao-20261012-<run>`, tags próprias em `ED_BACKEND_IMAGE`/`ED_FRONTEND_IMAGE`, provider desativado e chave vazia. Portas ocupadas exigem override privado com `ports: !override`, allowed origins e base URL correspondentes. Confira uma subnet livre antes de escolhê-la; não altere configuração global ou recursos de outra execução. Faça cleanup somente de nomes/labels criados por esta rodada.

Arquivos preenchidos, bundles e logs privados ficam fora do Git. Publique somente fixtures sintéticas e recibos curados com comandos, ambiente, hashes, denominadores, limites e cleanup. O scan redigido usa `.gitleaks.toml` no snapshot completo e histórico, sem ampliar exceções.

O [recibo da primeira evolução](../evidence/evolution-20261012/verification.json) separa as execuções sobre seus dois candidatos congelados. A única mudança entre eles foi uma correção de tipagem no executor adversarial, que teve seus testes e recibo repetidos. Os arquivos do workbench, backend e frontend permaneceram idênticos entre aqueles dois candidatos. As [capturas](../evidence/evolution-20261012/screenshots.json) e o [relatório de contratos](../evidence/evolution-20261012/adversarial-contracts.json) identificam seus inputs e limites. Naquela execução, o Docker local falhou antes de criar recursos; os gates PostgreSQL e da aplicação completa passaram no CI isolado da branch. A [rodada seguinte de UI/UX](../uiux-review-20261012.md) usa uma stack local própria e novas evidências.

## Decisões técnicas

A [revisão de UI/UX](../uiux-review-20261012.md) registra a comparação de 12/10/2026. Erros apontam o campo e direcionam o foco; achados críticos usam checkboxes. “Exportar submissão” produz um arquivo, e a importação autoritativa continua na CLI. A interface precisa de JavaScript; sem ele, a orientação apresenta o caminho pela CLI. O ensaio de CSS zoom verifica layout e não constitui zoom nativo do navegador.

O modelo de [respostas do Argilla](https://github.com/argilla-io/argilla/blob/develop/argilla/src/argilla/records/_resource.py#L328) separa respostas por pergunta/usuário de sugestões automáticas e permite exportação. Adotamos esse mecanismo de dados em arquivos próprios. O [projeto](https://github.com/argilla-io/argilla) declara manutenção com correções, sem novas funcionalidades. Não instalamos a plataforma nem copiamos seu código.

[Label Studio](https://github.com/HumanSignal/label-studio), Apache-2.0, é uma alternativa de anotação e [exportação](https://labelstud.io/guide/labeling). O desenho dos ataques segue a fronteira de [conteúdo não confiável do Promptfoo](https://www.promptfoo.dev/docs/red-team/plugins/indirect-prompt-injection/), sem geração remota ou CLI adicional. [Inspect](https://github.com/UKGovernmentBEIS/inspect_ai) oferece tarefas e [scorers](https://inspect.aisi.org.uk/scorers.html); um scorer não substitui anotação humana. Nenhum desses pacotes foi adicionado às dependências ou altera a licença MIT do EvidenceDesk.
