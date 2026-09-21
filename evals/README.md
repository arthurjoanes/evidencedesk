# Avaliações sem confundir teste de plataforma com qualidade da IA

`metrics.py` calcula funil completo, recall/MRR/nDCG, abstenção correta/indevida, suporte humano, cobertura e gates com denominadores. Um caso com timeout continua no sucesso ponta a ponta. IDs duplicados não rendem relevância extra. Rótulos sintéticos não contam como adjudicação humana.

`build_dataset.py` prepara 120 grupos (60 dev, 60 reservados), separados da demo e do treino, com eventos, snapshots, cobertura, mapas e documentos próprios. Metade do reservado representa novas instâncias de famílias conhecidas; metade contém famílias reservadas. Linhagens, incidentes e paráfrases não cruzam splits. Referências são sintéticas e não adjudicadas; ainda é necessária revisão humana antes dos gates semânticos. Perguntas e respostas esperadas não integram o texto das fontes.

O seed e a ingestão da aplicação não importam este diretório. Referências e rótulos não vão para prompts. Fontes de cada caso só podem ser disponibilizadas à pipeline depois de separadas dos golds. No teste final, chunking e truncamento não consultam o trecho esperado.

O teste de contratos executa offline e sem pesos ou segredos:

```powershell
.venv/Scripts/python.exe -m pytest evals/test_metrics.py
```

Baseline de produto é PostgreSQL FTS; não chamar um ranking por palavras em Python de FTS/BM25. Comparar lexical, vetor exato, RRF e reranker nos mesmos candidatos/recursos. Executar geração Azure somente com orçamento aprovado e registrar deployment/configuração/tokens; testes MockTransport comprovam contrato, não qualidade do provedor.

Antes de uso do reservado, congele config e hashes, registre responsável, horário, propósito e versão no ledger. A inspeção para corrigir falhas aposenta o conjunto como teste não visto: ele passa a regressão, e novos grupos são necessários para uma avaliação final futura. O rascunho presente não serve como certificação de qualidade nem de segurança universal.

Gate humano requer pelo menos 30 respostas de 15 incidentes independentes, cobrindo categorias semânticas, conforme especificação. Sem isso o estado é inconclusivo. Reamostrar incidentes/grupos para intervalos; citações do mesmo caso não são observações independentes.

Os denominadores são explícitos em `metrics.py`:

| Medida | Denominador e tratamento de ausência |
|---|---|
| Sucesso ponta a ponta | Todos os casos planejados, incluindo falhas e não executados. Resposta a caso respondível ou abstenção a caso não respondível conta como sucesso operacional; suporte semântico é medido separadamente. |
| Recall/MRR/nDCG@10 | Média por caso com ao menos uma referência relevante; lista vazia recebe zero. Duplicatas não geram crédito. Sem positivos, a medida é indefinida e não passa gate. |
| Abstenção correta | Todos os casos declarados não respondíveis, inclusive os que falharam. |
| Abstenção indevida | Todos os casos respondíveis; falha não é reclassificada como abstenção. |
| Precisão de suporte | Alegações/citações com rótulo humano, dentro de respostas adjudicadas. Anotação sintética não entra. |
| Cobertura útil | Fatos exigidos nas respostas adjudicadas; numerador são fatos efetivamente cobertos. |
| Concordância numérica | Números comparados com resultado determinístico; sem comparação o gate fica inconclusivo. |

Gates atuais: recall >=0,85; suporte humano >=0,90; abstenção correta >=0,80; abstenção indevida <=0,20; cobertura útil >=0,80; números verificados concordam integralmente. Gates de retrieval/abstenção só concluem quando todos os casos foram executados. Os gates `known_tenant_isolation` e `valid_citations` representam somente verificações explicitamente registradas: um caso testado sem falhas não prova cobertura universal dos demais. Reporte também quantos casos tiveram cada checagem.

O laboratório de reranking usa outro dev: trinta grupos, oito pares por grupo e quatro documentos relevantes/contextuais por pergunta. Recall considera relevância >0; nDCG usa graus 1 e 0,5. A média é por pergunta, não por par. Base e candidato recebem os mesmos vinte candidatos recuperados em cada rodada. Intervalo de ganho usa mil reamostragens pareadas de grupos, seed42; p95 é o percentil das medianas de três repetições por pergunta após warmup, sem incluir download/carregamento. Não confundir esse p95 com latência ponta a ponta do produto. O pico RSS do processo é cumulativo entre base/candidato e não permite atribuir a diferença de memória exclusivamente a um modelo.

O experimento de ranking preserva o corpus original de 124 documentos. A divisão documental `utf8-bytes-352-v2` adicionada ao produto depois da medição muda as unidades de recuperação: a validação de tokens não atualiza nem substitui o benchmark de qualidade. Uma comparação sobre esse corpus novo precisa de novas referências de spans, frozen corpus e relatório separado, sem tocar no conjunto reservado para ajustar o pipeline.
