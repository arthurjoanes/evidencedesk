# Auditoria do conjunto sintético v2

Revisão por agente em 21/09/2026, antes de carregar pesos e treinar. Não houve adjudicação humana. O conjunto inicial de JSON operacional foi substituído porque não representava os documentos recuperados em produção.

O alvo é relevância documental para a pergunta sobre um pedido específico. As duas notas desse pedido têm grau 1, inclusive a que contesta a hipótese. Procedimento e guia de coleta têm grau 0,5; notas de outro pedido explicitamente sem relação têm grau 0. Documentos de RH e decoração têm grau 0. Isso não ensina conciliação, causalidade ou validade factual: essas decisões continuam fora do reranker.

Os negativos difíceis compartilham tema e vocabulário com a consulta. A ausência de relação é uma premissa do gerador, verificável nos textos; em produção pedidos diferentes poderiam ter dependência comum, por isso esta regra de rótulo não pode ser aplicada automaticamente a dados reais. O verificador percorre todos os pares, rejeita referência do pedido consultado em negativos difíceis e requer a referência nos positivos.

São 150 grupos de treino e 30 grupos dev, com linhagens de casos disjuntas. Quatro documentos gerais são compartilhados de forma explícita; o resultado representa novos casos em uma base parcialmente conhecida, não generalização para documentação inteiramente nova. As duas famílias reservadas da avaliação final não são importadas. O conjunto reservado de avaliação não será executado neste experimento.

Há cinco moldes de pergunta e oito famílias, com forte repetição de texto. O resultado pode refletir identificação de referências e memorização do formato. Mesmo com ganho de ranking, o candidato permanece sem promoção até avaliação semântica humana e comparação externa adequada. O relatório deve divulgar também perda de recall do recuperador, regressões por grupo, latência e memória.

Fontes desta seção, conferidas em **22/09/2026**: [protocol.json](protocol.json) · [20260921T074245Z-train-manifest.json](reports/20260921T074245Z-train-manifest.json).
