# Observabilidade local

Ative apenas quando API/worker estiverem prontos: `python scripts/ops.py --observability start`. O override liga OTLP HTTP em `collector:4318` e inicia o perfil. O modo padrão continua sem esses serviços. Grafana: http://127.0.0.1:3206 (admin / ed_grafana_local_demo); Prometheus: http://127.0.0.1:9106; Alertmanager: http://127.0.0.1:9196; entregas locais: http://127.0.0.1:9187/events. Todos são administração local, separados da sessão do analista. Nenhum alerta é enviado por email/chat externo.

Prometheus lê `/metrics` com bearer; não reutiliza cookie de analista. Se trocar `ED_METRICS_TOKEN`, crie arquivo protegido com o mesmo valor e configure `ED_METRICS_TOKEN_FILE` para esse caminho; o arquivo demo contém somente um valor público. Grafana tem senha configurável por `ED_GRAFANA_PASSWORD`; trocar variável não gira automaticamente a senha de um banco Grafana já inicializado. Collector, Loki e Tempo não têm porta publicada. O socket Docker não é montado.

Traces/logs usam filas limitadas e timeout de exportação. O collector mantém somente atributos aprovados e substitui corpo de log por uma descrição fixa; evento/código/correlação ficam estruturados. Prompts, respostas, query strings, headers, texto de documento e stack traces livres não são exportados. A instrumentação da aplicação deve também evitar esse conteúdo antes do collector: sanitização tardia não protege stdout. Os IDs só entram em trace/log permitido, nunca labels de métricas.

Prometheus, Loki e Tempo retêm até três dias; Prometheus também tem teto de 256 MB. Limites de ingestão/retention não equivalem a quota física de todos os volumes. O receiver mantém apenas as últimas 200 entregas na memória e stdout rotacionado; copie metadados do ensaio para evidência antes de reiniciá-lo. Nenhum desses sistemas é a fonte de verdade do dossiê ou ledger de custos.

## Indisponibilidade

`EvidenceDeskUnavailable` depende de probe HTTP fora do processo da API. Confira readiness, migração e DB antes de reiniciar. A recuperação exige a resposta 200 observada e a entrega `resolved` no receiver. Este probe divide o host com o produto e não detecta de dentro a perda total do host; monitoramento externo real continua necessário em hospedagem.

## Telemetria ausente

`EvidenceDeskTelemetryMissing` verifica scrape/probe ausente ou falho. Confira token, rede e collector separadamente da API. Um painel vazio não representa zero erro. `absent()` está coberto por teste de regra. Nenhuma telemetria pode ser considerada válida apenas porque o YAML passou no validador.

## Erros e fila

Erro de servidor acima de 5% exige pelo menos 20 requisições de produto em 5 min e persistência por 2 min. `/health/*` e `/metrics` ficam fora desse numerador e denominador; prontidão tem seu próprio alerta. Exiba também 4xx/429/503 e volume total: não esconda rejeições fora do denominador. Fila envelhecida e heartbeat vencido exigem verificar leases, capacidade e jobs retry/dead antes de escalar. Não libere locks manualmente nem reenvie trabalho sem chave idempotente. Ingestão pendente sem publicação sinaliza problema; uma coleção sem trabalho novo não dispara alerta de paralisação só por estar quieta.

## Provedor e orçamento

Três timeouts em cinco minutos são sinal de investigação, não autorização para aumentar retries. Confira o estado `unknown` de consumo; não devolva reserva por TTL. Orçamento >=80% gera aviso, mas o bloqueio efetivo vem da admissão da aplicação. Alertmanager/Azure Budgets não interrompem chamadas por conta própria. Sem provedor configurado, a baseline manual permanece o caminho operacional.

`ed_provider_failures_total{outcome="timeout"}` expõe o total persistido de tentativas, sem somar novamente a cada scrape. `ed_provider_call_records{state}` é um gauge do estoque atual de chamadas por estado. Restauração/remoção de histórico pode diminuir o contador; Prometheus interpreta a queda como reset. O histórico de chamadas precisa ter retenção maior que a janela de alerta; esse contador não substitui o ledger financeiro.

## Armazenamento

Menos de 1 GiB livre sinaliza risco antes de publicar novos objetos. Não apague arquivos diretamente do volume: eles podem ter referência em revisão/snapshot. Use retenção/exclusão da aplicação e backup. O espaço observado é do filesystem do volume, que pode compartilhar o disco do daemon.

## Qualidade

`EvidenceDeskQualityRegression` exige um resultado executado reprovado. `EvidenceDeskQualityUnknown` inclui inconclusivo, ausência e avaliação com mais de sete dias. A idade é política inicial explícita, ajustável por evidência de uso; não prova drift. Baixo volume/amostra humana insuficiente continua inconclusivo, sem fabricar 100%. O gate offline, o canário operacional e feedback humano têm denominadores diferentes.

Acompanhe disponibilidade alvo 99,5% em 30 dias, p95 de admissão <500 ms e espera de fila p95 <10 s apenas como objetivos até existir janela medida. O dashboard de latência HTTP total não comprova sozinho o SLO de admissão. Um ensaio curto deve relatar taxa ofertada/admitida, falhas, p95/p99, cenário, réplicas, recursos e tempo; não anuncia SLO mensal nem disponibilidade de produção.

## Evidência e fontes

`python scripts/check_infra.py` valida sete configurações e dez cenários de alertas com ferramentas fixadas. [A verificação em execução](../evidence/observability-runtime.json) consulta métricas protegidas, uma requisição real registrada em Loki e seu trace no Tempo. [A smoke Azure](../evidence/azure-smoke-trace.json) confirma a relação HTTP→job→modelo; a primeira configuração removeu os metadados específicos do adapter, limitação registrada sem repetir a chamada paga. [As entregas locais](../evidence/alert-deliveries.json) preservam disparo, agrupamento e recuperação observados. Esses ensaios não adjudicam a qualidade semântica da IA.

`scripts/check_observability.py` usa as dependências do backend dentro da rede Compose; não requer ferramentas adicionais no host. Faça a consulta com o serviço `api` em um container one-off, montando `scripts` como `/ops:ro` e executando `python /ops/check_observability.py`. O script não chama inferência. [Configuração do collector](https://opentelemetry.io/docs/collector/configuration/), [OTLP nativo do Loki](https://grafana.com/docs/loki/latest/send-data/otel/otel-collector-getting-started/), [Tempo monolítico](https://grafana.com/docs/tempo/latest/configuration/) e [Alertmanager](https://prometheus.io/docs/alerting/latest/configuration/) orientam este perfil. Tempo3 usa `backend_scheduler`/`backend_worker` para retenção e, em modo monolítico, não exige Kafka. Versões e digests estão no Compose.

## Coleta final e fronteiras dos ensaios

[A coleta da imagem final](../evidence/observability-runtime-final.json) repetiu HTTP→SDK→collector→Loki/Tempo, autorização das métricas e entrega de qualidade desconhecida. A primeira tentativa encontrou o log antes do trace e recebeu 404 do Tempo; o mesmo trace depois retornou 200. O probe passou a esperar o exporter de traces de forma independente e limitada, com duas regressões. [A tentativa inicial](../evidence/observability-final-attempt-1.json) foi preservada.

| Cenário                        | Evidência atual                                                                                    |
| ------------------------------ | -------------------------------------------------------------------------------------------------- |
| API indisponível e recuperação | Alerta entregue e resolvido em runtime local durante manutenção                                    |
| Qualidade desconhecida         | Entrega real ao receiver; não confundir com qualidade aprovada                                     |
| Fila antiga                    | Job operacional sintético criado no instante real, com disparo e resolução entregues ao receptor   |
| Coleta interrompida            | Collector parado; probe independente observou a falha e o retorno, com alerta entregue e resolvido |
| Worker parado                  | Heartbeat vencido após parada real, com disparo e resolução entregues                              |
| Modelo indisponível            | Parada real do perfil opcional, disparo e resolução entregues; sem inferência                      |
| Saturação HTTP                 | Carga isolada, com falhas iniciais e repetição corrigida; não ligada ao receiver do principal      |

`ed_budget_utilization_ratio` usa a mesma `budget_position` da admissão: consumo reportado do mês UTC e reservas pendentes inclusive de meses anteriores. Consumo desconhecido não é devolvido por virar o mês. `EvidenceDeskModelUnavailable` observa o readiness do modelo apenas quando o target do perfil opcional está configurado.

## Modelo local

A configuração base monta `model-targets.disabled.json` (lista vazia). Quando o serviço estiver intencionalmente habilitado, acrescente `infra/compose/observability-ml.yaml` à configuração de observabilidade: ele monta o target de `http://models:8090/healthz`. Não ative o target para um perfil que deve ficar desligado. O token interno precisa ter pelo menos 24 caracteres e entra via configuração protegida. A inspeção de readiness é interna e não executa inferência.

O collector expõe `/` em 13133 somente na rede Compose. Seu health_check prova presença/prontidão do processo, não entrega de todos os exporters. Prometheus e Blackbox continuam operando quando ele para; a correlação real de log/trace permanece uma verificação independente.

[O ensaio worker/fila/collector](../evidence/alert-recovery-worker-queue-collector.json) preserva uma falha na recuperação automática: Compose start tentou executar também um migrador antigo via depends_on. Os dois containers de runtime foram retomados diretamente, com ambiente/segredos preservados, e os três alertas resolveram. O helper foi corrigido para selecionar somente containers existentes. Não classificar essa tentativa como recuperação automática perfeita.

[O ensaio de modelo](../evidence/alert-recovery-model.json) usou o helper corrigido e recuperou automaticamente o serviço. O receiver recebeu `firing` às 08:44:25 UTC e `resolved` às 08:45:10 UTC. O contador de chamadas permaneceu em 1 antes/depois, sem nova geração Azure ou inferência local. Depois da recuperação, o modelo foi desligado voluntariamente e seu target removido, preservando o perfil inicial. [A coleta após todos os ensaios](../evidence/observability-runtime-closed.json) confirmou novamente métricas, probe independente do collector e correlação HTTP→log→trace.
