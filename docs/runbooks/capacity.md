# Capacidade local: o que foi medido

O ensaio usa namespace `pf-evidencedesk-capacity-review006`, volumes próprios e portas efêmeras de API em loopback. Provedor desativado, chave vazia e zero chamadas de modelo em todas as fases. O corpus inicial contém os seis pacotes sintéticos e 30 incidentes; o ambiente principal não recebeu carga. [O manifesto](../evidence/capacity-summary.json) liga os arquivos brutos, hashes e as duas imagens congeladas.

Fontes desta seção, conferidas em **22/09/2026**: [capacity-summary.json](../evidence/capacity-summary.json).

## Leituras HTTP

`scripts/capacity_http.py` oferece 10 requisições/s durante 20 s, totalizando 200 por execução. Distribui os dois tenants e quatro rotas (`collections`, lista/detalhe de incidentes e imports) pelas réplicas. Não há load balancer sob teste: o gerador roteia explicitamente. Cada API tem 1 CPU/512 MiB; o PostgreSQL único tem 1 CPU/512 MiB. Pool: 4 conexões por API, sem overflow.

O gerador é aberto, com no máximo 32 requisições em voo. Atrasos do agendador e descartes do cliente são publicados, evitando esconder sobrecarga ao esperar a resposta anterior. Só login e uma leitura de collections ficam fora da medição. O primeiro cálculo de resumo entra na janela; o cache começa frio.

| Versão / APIs | HTTP 200 / ofertadas | HTTP 500 | Descartes do cliente | p50 / p95 / p99, todas as tentadas |
| ------------- | -------------------: | -------: | -------------------: | ---------------------------------- |
| Antes, 1      |               73/200 |       36 |                   91 | 6458 / 11008 / 11433 ms            |
| Antes, 2      |              130/200 |       14 |                   56 | 4306 / 8432 / 9986 ms              |
| Corrigida, 1  |              200/200 |        0 |                    0 | 17 / 810 / 1409 ms                 |
| Corrigida, 2  |              200/200 |        0 |                    0 | 17 / 345 / 2004 ms                 |

Os percentis de sucesso estão separados nos JSONs; uma falha não desaparece do denominador. O p95 de uma API permanece acima da referência de 500 ms. Duas APIs reduziram o p95, mas tiveram p99 maior durante o frio: não há ganho linear demonstrado. O objetivo original de **admissão** <500 ms não foi medido por essas leituras, nem há janela suficiente para afirmar disponibilidade de 99,5% em 30 dias.

O gargalo era `incident_payload`: a lista recalculava conciliação completa para cada incidente. O cache agora guarda apenas contagens/cobertura, por tenant, snapshot, janela e revisão da política; tem TTL de 60 s, 128 entradas e no máximo 64 KiB por entrada. `single-flight` evita trabalho idêntico simultâneo. Autorização é consultada sempre; dossiês/runs não entram no cache. Esgotamento do pool retorna 503 seguro e retryable, sem expor traceback. Os JSONs de falha originais continuam disponíveis.

Entre versões, os ensaios de fila adicionaram documentos sintéticos e dossiês manuais ao banco isolado. O corpus grande de eventos não mudou, mas não é um experimento com estado físico de banco exatamente idêntico. Os testes unitários/integrados isolam reuso, TTL, invalidação e autorização; a comparação de carga mostra efeito combinado das versões congeladas, não atribuição causal perfeita de cada milissegundo.

Fontes desta seção, conferidas em **22/09/2026**: [capacity_http.py](../../scripts/capacity_http.py) · [capacity_jobs.py](../../scripts/capacity_jobs.py) · [capacity-summary.json](../evidence/capacity-summary.json).

## Fila real, dois tenants

`scripts/capacity_jobs.py` prepara revisão manual por uma pessoa diferente e enfileira 8 exports HTML + 8 ingestões Markdown de aproximadamente 31 KiB. Aurora recebe 12 jobs, Horizonte recebe 4; Aurora entra primeiro. Cada worker tem 1 CPU/512 MiB. Nenhuma geração fake é apresentada como IA.

| Versão / workers | Concluídos | Tempo após liberação* | Primeira conclusão Aurora / Horizonte |
| ---------------- | ---------: | --------------------: | ------------------------------------- |
| Antes, 1         |      16/16 |                8,36 s | 1,99 / 2,05 s                         |
| Antes, 2         |      16/16 |                5,66 s | 1,84 / 1,89 s                         |
| Corrigida, 1     |      16/16 |                7,16 s | 2,10 / 2,15 s                         |
| Corrigida, 2     |      16/16 |                5,69 s | 1,96 / 2,00 s                         |

\* Inclui partida dos containers e polling de observação. Os tempos `queue_seconds` incluem a preparação deliberada do backlog; não são latência contínua de produção. Todos os jobs tiveram uma tentativa. As 32 exportações entre as quatro execuções foram baixadas, comparadas ao SHA-256 persistido e verificadas quanto a escape de HTML; as 32 ingestões publicaram snapshots. O tenant menor progrediu cedo, mas um lote finito não prova ausência de starvation em qualquer carga.

Fontes desta seção, conferidas em **22/09/2026**: [capacity_http.py](../../scripts/capacity_http.py) · [capacity_jobs.py](../../scripts/capacity_jobs.py) · [capacity-summary.json](../evidence/capacity-summary.json).

## Recursos e limites da conclusão

Treino/modelos ficaram parados durante as janelas. Outros projetos do host continuaram ativos e podem interferir. A amostra original mostra API saturada; as amostras finais estão datadas. A de uma API corrigida ocorreu **depois** da janela e não representa pico/média. A de duas APIs caiu dentro da janela; APIs em cerca de 128 MiB e CPU de 4–6% naquele instante. Tetos reservados não equivalem a consumo real.

As imagens testadas foram `40da9ef4…` (antes) e `927be276…` (corrigida); hashes completos estão no manifesto. A imagem final principal recebeu ainda ajustes posteriores de parsing/proveniência e não foi submetida a outro benchmark. Não transferir esses números automaticamente para Azure, arquivos máximos, PDFs/OCR, inferência, carga sustentada ou produção.

Ao terminar, foram parados apenas os containers do namespace de capacidade; volumes foram preservados. Não há `prune` nem agendamento de carga.

Fontes desta seção, conferidas em **22/09/2026**: [capacity_http.py](../../scripts/capacity_http.py) · [capacity_jobs.py](../../scripts/capacity_jobs.py) · [capacity-summary.json](../evidence/capacity-summary.json).
