# Laboratório de retrieval e reranking

O ambiente atual usa `pf-evidencedesk-ml:torch2.14-cu130-shards-v1`. O build mantém o lock e aplica um backport identificado por hash para CVE-2026-69112, com 15 testes reais do loader Accelerate. Veja [correção, reprodução e limites](../docs/ml-checkpoint-security.md). Os resultados de treino e qualidade abaixo são históricos; a correção não promove nem retreina o candidato.

O experimento foi executado em 21/09/2026, sem chamadas Azure. O candidato continua **não promovido**. Todos os dados são originais e sintéticos; nenhuma anotação foi adjudicada por humano e o conjunto reservado da avaliação final não foi aberto.

E5: `intfloat/multilingual-e5-small`, revisão `614241f622f53c4eeff9890bdc4f31cfecc418b3`, MIT, 384 dimensões. Reranker base: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, revisão `1427fd652930e4ba29e8149678df786c240d8825`, Apache 2.0. Downloads restringem arquivos e geram hashes; não executam código remoto. Pesos e checkpoints ficam nos volumes Docker, fora do Git e do OneDrive.

O dataset tem 1.200 pares/150 grupos de treino e 240 pares/30 grupos dev. Inclui documentos que contestam a hipótese, referências de contexto, negativos difíceis de outro pedido e negativos sem relação. Cinco moldes de pergunta e oito famílias tornam esse um experimento de engenharia reproduzível, com diversidade limitada. Quatro referências gerais são compartilhadas explicitamente; casos/linhagens específicos são disjuntos. Veja [auditoria dos rótulos](negative-label-audit.md) e [protocolo congelado](protocol.json).

Treino real: uma época, 75 passos, batch 2 com acumulação 8, float32, comprimento máximo 512, seed 42 e learning rate 2e-5. Na RTX 5070 Ti, PyTorch 2.14.0+cu130 executou 34,65 segundos de treino (38,99 até salvar checkpoint), com pico de RSS 2.669,7 MiB e 2.228,9 MiB de VRAM alocada. O container tinha duas CPUs e teto de 3 GiB sem swap adicional. MLflow local registrou parâmetros, hashes e métricas. [Manifesto do treino](reports/20260921T074245Z-train-manifest.json).

A recuperação executou E5 e PostgreSQL FTS/pgvector reais sobre 124 documentos dev. Cada consulta gerou candidatos por busca; o reranker apenas os reordenou. Nenhum positivo ausente foi inserido usando o gold. Ambas as rodadas permanecem publicadas:

| Medida | Planner AND original | Planner OR com até 16 lexemas |
|---|---:|---:|
| nDCG@10 lexical | 0,0000 | 0,4949 |
| nDCG@10 E5 | 0,5663 | 0,5663 |
| nDCG@10 RRF | 0,5663 | 0,5738 |
| nDCG@10 reranker base | 0,6906 | 0,7011 |
| nDCG@10 candidato | 0,7818 | 0,8047 |
| Ganho pareado candidato/base | +0,0912 | +0,1036 |
| Recall@10 candidato | 0,4917 | 0,5167 |
| p95 base/candidato | 109,02/143,67 ms | 101,06/101,68 ms |
| Razão p95 candidato/base | 1,318 — falhou limite 1,25 | 1,006 — passou nesta rodada |

O AND da pergunta inteira era restritivo demais; esse achado motivou `lexical-v2` no core. A rodada com OR usa o mesmo candidato e dev, sem retreinamento, com candidatos diferentes. Não substitui a rodada anterior nem comprova estabilidade de latência. Bootstrap pareado sintético de 30 grupos produziu intervalos de ganho [0,0611; 0,1248] e [0,0737; 0,1370]; a amostra não representa qualidade em produção. O recall continua limitado e a análise de regressões semânticas exige revisão humana. Não houve promoção automática ou execução oportunista do holdout.

Relatórios: [retrieval original](reports/retrieval-dev.json), [retrieval OR](reports/retrieval-dev-lexical-v2.json), [comparação original](reports/reranker-comparison.json), [comparação OR](reports/reranker-comparison-lexical-v2.json), [hashes exportados](reports/index.json). O primeiro smoke treinou mas falhou no caminho de artefatos MLflow somente leitura; seu manifesto de falha foi preservado. O segundo smoke e o treino completo concluíram após direcionar artefatos para `/runs`.

Para reproduzir no perfil GPU:

```powershell
docker compose -f experiments/compose.yaml build lab
docker compose -f experiments/compose.yaml --profile setup run --rm prepare
docker compose -f experiments/compose.yaml run --rm lab
docker compose -f experiments/compose.yaml run --rm lab python experiments/download_models.py
docker compose -f experiments/compose.yaml run --rm lab timeout 900 python experiments/train_reranker.py --mode smoke --output /runs
docker compose -f experiments/compose.yaml run --rm lab timeout 3600 python experiments/train_reranker.py --mode train --synthetic-labels-audited --output /runs
docker compose -f experiments/compose.yaml --profile retrieval up -d --wait retrieval-db
docker compose -f experiments/compose.yaml run --rm lab python experiments/retrieve_dev.py --planner lexical-v2
# Troque <run> pelo diretório informado pelo treino:
docker compose -f experiments/compose.yaml run --rm lab python experiments/compare_rerankers.py --candidate /runs/<run>/candidate --retrieval /runs/retrieval-dev-lexical-v2.json --output /runs/reranker-comparison-lexical-v2.json
```

`requirements-ml.lock` registra todas as versões resolvidas do ambiente executado; a imagem final instala esse lock. `requirements-ml.in` descreve dependências diretas. A validação leve `python experiments/train_reranker.py --mode validate` não importa Torch. Downloads são um comando explícito; treino usa somente cache por padrão. Antes de iniciar, confira RAM disponível no WSL, VRAM e outros processos. O limite de container não substitui essa coordenação. Depois das medições, os containers do laboratório foram parados, com volumes preservados.

O rebuild histórico de reprodução foi executado a partir do lock sem alterar versões. A imagem então validada foi `pf-evidencedesk-ml:torch2.14-cu130-locked-20260921`; o default atual com backport está descrito acima, e override explícito usa `ED_ML_IMAGE`. Image ID observado: `sha256:54acfbc838b283a957207ccc5029c91c34355c382f4052bb1e92a72d3820440a`. A tag anterior e seu image ID foram preservados. Os 116 pacotes conferem com o lock, cujo SHA-256 é `fe6a15df74d68958ce9ebc2d84b1cc48e9f508a6b7732f8b0fa52825369a0249`; `pip check` passou. O serviço reconstruído passou embeddings, reranking, readiness e autenticação de métricas por HTTP real, com as mesmas revisões e dimensão da primeira smoke. Ficou limitado a 3 GiB/duas CPUs e foi parado após a prova. [Build final](reports/ml-final-build.json), [ambiente](reports/environment-check-locked.json), [smoke separada](reports/model-service-smoke-locked.json).

A primeira tentativa de build sem rede falhou na resolução/revalidação da URL do wheel Torch. A reinstalação dos pacotes exatos foi então permitida e reutilizou cache onde disponível. Nenhum peso novo foi baixado e não houve treino ou Azure. A smoke verifica reprodução funcional; seu tempo isolado não é novo benchmark. A imagem ML não recebeu scan de vulnerabilidades nesta etapa, portanto essa prova não significa aprovação de segurança da imagem.

O [serviço privado de modelos](../docs/model-service.md) passou uma smoke HTTP real com E5/reranker **base**, autenticação e métricas. Continua separado do core; somente o perfil ML carrega Torch. [Evidência da smoke](reports/model-service-smoke.json).

Depois do benchmark, o produto recebeu chunks `utf8-bytes-352-v2`; essa mudança não altera os relatórios anteriores. A [verificação de tokenizers](reports/chunk-policy-tokenizers.json) usou somente os noventa documentos da demo e probes Unicode, sem pesos, Azure ou gold reservado: 180 chunks, máximos80 tokens E5 e97 no par para a pergunta padrão. É uma verificação de compatibilidade, não nova medição de qualidade. Reavaliar retrieval sobre os novos spans exige corpus/referências/release próprios.

O [manifesto público](../model-manifest.json) reúne  hashes de modelos, ambiente, código e evidências medidas. Os oito arquivos do candidato foram [identificados por SHA-256](reports/candidate-files.json), sem exportar pesos. Para atualizar o índice após uma revisão intencional, rode `python experiments/build_manifest.py`; não substitua silenciosamente relatórios antigos.

Fontes: [PyTorch e CUDA](https://pytorch.org/get-started/locally/), [índice oficial CUDA 13.0](https://download.pytorch.org/whl/cu130/torch/), [NVIDIA WSL](https://docs.nvidia.com/cuda/wsl-user-guide/), [E5](https://huggingface.co/intfloat/multilingual-e5-small), [reranker](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1), [treino de CrossEncoder](https://sbert.net/docs/cross_encoder/training_overview.html).
