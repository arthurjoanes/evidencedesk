# Retenção e quota de armazenamento

O perfil local possui uma rotina executável de retenção, com fila durável de objetos e liberação idempotente de quota. Não há um agendador iniciado automaticamente: o operador chama uma varredura limitada por tenant ou a inclui no agendador de sua implantação. Ela não executa inferência nem remove documentos/dossiês publicados por idade.

## Política do laboratório

| Recurso | Regra padrão |
| --- | --- |
| Importação abandonada, rejeitada ou encerrada sem publicação | 24 horas desde a última atividade registrada; sem upload vivo e sem job de ingestão ativo |
| Objetos sem referência no namespace privado conhecido | Pelo menos 24 horas de idade; sem produtor ativo nem referência viva |
| Exportação HTML | `expires_at` definido pelo publicador, atualmente 24 horas; a revisão continua no banco |
| Eventos de progresso | 7 dias; apenas quando o job também terminou há pelo menos 7 dias |
| Auditoria | Mínimo de 90 dias, com função SQL restrita ao tenant e remoção em lotes |
| Fontes, snapshots, dossiês, ledger de chamadas e ledger de exclusões | Não expiram por esta rotina |

`--temporary-hours`, `--progress-days` e `--audit-days` permitem retenção maior, respeitando pisos de 24h/7d/90d. `--batch-limit` vale 100 por padrão, entre 1 e 1000; limita cada classe de candidatos, a limpeza física e as remoções de histórico. `--scan-limit` vale 1000, entre 1 e 10000; limita arquivos inspecionados por varredura. O cursor de diretório fica no banco e avança entre execuções, voltando ao início ao terminar. Novos arquivos anteriores ao cursor entram no próximo ciclo.

Logs e traces têm configuração própria no [runbook de observabilidade](observability.md). Não são apagados por esta rotina. O adaptador Azure Blob permanece uma preparação separada: esta implementação de retenção usa o armazenamento privado **local**.

## Executar e interpretar

Com a imagem atualizada e migrações aplicadas, execute no ambiente que já possui a configuração da API e o mesmo volume privado:

```console
python -m evidencedesk.retention --tenant ID_DO_TENANT --batch-limit 100 --scan-limit 1000
```

Para o host, configure explicitamente `ED_DATABASE_URL` e `ED_STORAGE_ROOT` do mesmo laboratório antes do comando. O banco e o volume precisam pertencer à mesma instância; o comando não descobre ou corrige essa associação. Uma manutenção global ativa bloqueia a varredura.

O JSON informa importações/exports planejados, quantidade inspecionada, cursor, truncamento da varredura, histórico removido, bytes liberados e cada operação de limpeza. `blocked_or_failed>0` produz exit code 1. Nesse caso, `storage_cleanup.error_code` diferencia objeto em uso de falha física; os caminhos e a quota ficam disponíveis para nova tentativa. Não interprete uma varredura limitada sem candidatos como prova de que o armazenamento inteiro foi inspecionado.

## Invariantes e recuperação

A reserva começa na admissão do manifesto, inclusive para arquivos ainda não enviados. `import_entries.quota_bytes` identifica sua responsabilidade. `quota_released_at` é atualizado uma vez, na mesma transação que subtrai a quota do tenant. Não há truncamento artificial com `max(0, ...)`: uma inconsistência provoca falha do check de banco, em vez de produzir um saldo aparentemente correto.

`storage_cleanup` registra as chaves antes de eliminar referências. A exclusão de fonte, a retenção e o replay do ledger usam a mesma limpeza e o mesmo compare-and-set por entrada. Uma falha depois de remover alguns arquivos mantém a lista durável; arquivos já ausentes são tratados de forma idempotente. Se houver referência viva, produtor ativo, namespace incompatível ou symlink, a quota não é liberada. Tarefas bloqueadas não monopolizam o lote: tarefas com menos tentativas têm prioridade.

O PUT recebe e limita todo o corpo **antes** de adquirir o lock de publicação. Sob esse lock, confere a lease e grava apenas no disco local; nenhum recebimento de rede cliente ocorre dentro da transação. Um upload tardio não pode recriar bytes depois da expiração. Ao repetir uma tentativa não publicada, o objeto do token anterior é limpo antes de criar outro, preservando uma reserva por arquivo. PUT de arquivo já publicado confere o checksum sem gerar outro objeto.

A migração `0007` associa pedidos de exclusão existentes à fila, reconstrói a propriedade da quota por entrada e marca liberações já concluídas. O replay de exclusão continua exigindo janela de manutenção possuída e ledger íntegro; a alteração não remove essas verificações. Tombstones, revisões imutáveis e o incremento de `tenant_policy.revision` da exclusão foram preservados. Falhas originais de importação permanecem no diagnóstico quando seus bytes expiram.

## Verificação e limites

Os testes de `backend/tests/integration/test_retention.py` usam PostgreSQL descartável em 5547, role de aplicação/RLS e diretórios temporários. Cobrem reserva sem upload, rejeição, PUT repetido, produtor vivo, upload tardio, limpeza de token anterior, falha de disco, referências vivas, namespace de outro tenant, órfãos, cursor, corrida purge/retention, replay com quota, exports e pisos de auditoria/progresso. A regressão inclui administração e manutenção existentes. Nenhuma varredura foi executada sobre o corpus principal em 5546.

Na rodada local direcionada de 21/09/2026, **29 testes passaram em 24,61 s**, incluindo as regressões de administração, manutenção e revisão manual. O [JUnit preservado](../evidence/retention-integration.xml) identifica os casos. Este resultado não representa execução do CI nem ensaio de retenção em produção.

O lock por tenant serializa a verificação e o unlink local. Isso favorece correção neste laboratório; não é uma prova de throughput para milhões de objetos. A enumeração de diretórios precisa percorrer nomes anteriores ao cursor e ordenar entradas de cada diretório; `scan-limit` limita inspeções de arquivo e consultas ao banco, não todo o custo de listar o filesystem. Armazenamento remoto precisa de paginação própria, timeouts e coordenação durável de I/O antes de ativar retenção equivalente. Os limites da quota representam originais e reservas de importação; exports, resultados de IA, índices e metadados têm retenção/limites próprios, e não são apresentados como parte de um teto físico global de todos os volumes.
