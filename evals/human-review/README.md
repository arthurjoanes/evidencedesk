# Pacote para revisão semântica

**Problema central:** uma citação pode existir sem sustentar a frase que a usa. Esta revisão deve verificar suporte, contradição, omissão e abstenção antes de tratar um rascunho como evidência de qualidade.

**Estado: preparado, não executado.** Não há participantes, respostas adjudicadas ou aprovação do candidato neste pacote. A preparação conferiu somente os 60 casos de desenvolvimento e os hashes de suas fontes sintéticas. O conjunto reservado não foi aberto; seus nomes e hashes já publicados no manifesto não são julgamento de seu conteúdo.

## 1. Material disponível e o que ainda precisa ser congelado

O [índice do pacote](package.json) aponta os casos em [dev.jsonl](../data/dev.jsonl) e suas fontes. As oito famílias cobrem reentrega, atraso, ordem dos fatos, resultado incerto, reserva vencida, snapshot antigo, identidade divergente e procedimento obsoleto. Referências foram produzidas sinteticamente e precisam ser conferidas pelo revisor; não são rótulos humanos prontos.

Antes de gerar respostas, preencher o [formulário da rodada](round.template.json) com release, commit/imagem, corpus, política de chunks, parser/regras, retrieval e revisões dos modelos realmente utilizados. Congelar os casos planejados e a ordem da comparação. Respostas, erros, timeouts e casos não executados precisam permanecer no registro.

O pacote não contém saídas geradas de um modelo atual. Reutilizar números do laboratório sobre 124 documentos não avalia os chunks `utf8-bytes-352-v2`. Os manifests e critérios históricos permanecem em [experiments/protocol.json](../../experiments/protocol.json), [experiments/README.md](../../experiments/README.md) e [model card](../../docs/model-card.md).

## 2. Conduzir a revisão sem mostrar o gabarito ao sistema

1. Separar pergunta/fontes de referências e fatos esperados. Somente a primeira parte entra no fluxo avaliado. Golds, rótulos e fatos proibidos ficam com o avaliador.
2. Comparar a baseline manual/lexical e o candidato nos mesmos casos autorizados. Identificar os sistemas por códigos durante a revisão quando possível; registrar a ordem e qualquer ajuda recebida.
3. Guardar a resposta exata e as fontes efetivamente acessadas. Registrar IDs, spans, hashes, validade temporal e contexto do snapshot; não substituir uma fonte por outra mais conveniente depois de ler a resposta.
4. O revisor humano confere cada alegação pela [rubrica](rubric.json) e preenche um [formulário por resposta](response.template.json). Divergências e incertezas ficam explícitas.
5. Outro revisor resolve os desacordos, quando disponível. Se houver apenas um, declarar essa limitação; não inventar concordância entre avaliadores. Guardar julgamentos iniciais e decisão final.

O formulário usa um identificador de participante, sem exigir nome pessoal no repositório público. Arquivos preenchidos e respostas potencialmente sensíveis devem ficar no diretório privado da rodada. Publicar somente o resumo sanitizado autorizado.

## 3. Aplicar a rubrica

| Critério            | Pergunta de conferência                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------- |
| Suporte             | O trecho citado sustenta exatamente a alegação, no pedido e no período corretos?                                |
| Contradição         | Há evidência contrária que foi omitida ou apresentada como se concordasse?                                      |
| Cobertura           | Os fatos necessários à tarefa estão presentes, sem contar a mesma informação repetida como cobertura adicional? |
| Temporalidade       | Procedimento, snapshot e momento do fato permitem essa interpretação?                                           |
| Abstenção           | A resposta reconhece falta de evidência quando necessário, sem deixar de responder um caso sustentado?          |
| Números             | Valores e contagens concordam com a conciliação determinística identificada?                                    |
| Limite da conclusão | Uma observação virou causalidade comprovada, certeza de entrega ou instrução financeira sem suporte?            |

`supported`, `contradicted`, `insufficient` e `irrelevant` são rótulos por alegação. A justificativa precisa apontar a fonte/trecho; marcar uma caixa não basta. Um campo não avaliado fica `null`, e não zero ou aprovação.

## 4. Decidir com denominadores e limites

Usar os [critérios existentes](../README.md) e o [cálculo de métricas](../metrics.py), sem reduzir limiares depois de observar resultados. O gate humano exige pelo menos 30 respostas adjudicadas de 15 incidentes independentes e cobertura das categorias exigidas. Essa é uma condição mínima de elegibilidade, não garantia estatística de representatividade.

Mapear suporte para `human_support_labels` somente depois da adjudicação; manter os rótulos detalhados e justificativas como origem. Preencher `human_adjudicated=true` exige revisão humana efetivamente realizada. Timeouts e falhas continuam no denominador ponta a ponta. Reamostrar por incidente/grupo, sem tratar citações do mesmo caso como pessoas ou casos independentes.

A preparação e uma revisão em dev ajudam a melhorar o sistema; não são teste final não visto. Para usar o reservado, primeiro congelar a versão e registrar responsável, propósito e horário no ledger conforme o [protocolo](../README.md). Se ele for inspecionado para ajustar o sistema, perde o estado de não visto. A promoção continua uma decisão explícita, com os gates semânticos, operacionais e de recursos separados.
