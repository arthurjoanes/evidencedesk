# Backup consistente e restore fechado

O protocolo local para novas mutações, drena publicações/uploads e pausa coleta de objetos. Só então produz pg_dump binário e cópia dos objetos referenciados, com manifesto SHA-256. Temporários/órfãos não entram: um processo cancelado ainda pode terminar uma escrita privada antes de ter a publicação recusada, por isso o backup usa a lista estável de referências imutáveis do banco. O registro de exclusões fica em outro volume e não é retrocedido junto do backup.

Objetivos iniciais de laboratório: RPO de até 24 h com uma cópia diária operada e RTO de até 10 min para a massa demo. Não existe agendamento automático nem alegação de atingir esses valores antes de medi-los. Backups no mesmo host não protegem contra perda do host/disco. Uma política real exige cópia protegida independente e ensaio de recuperação desse local.

```powershell
python scripts/backup.py create C:\caminho-protegido\backups\ed-20260921
python scripts/backup.py verify-restore C:\caminho-protegido\backups\ed-20260921
```

A pasta do backup deve ser nova, fora do repositório e do OneDrive. Ela contém dados privados completos: trate-a como o banco de origem. Não publique o dump/tar no Git. O manifesto só é escrito ao terminar; diretório parcial sem manifesto válido nunca serve como backup aprovado. Erros de arquivo/hash/objeto ausente interrompem o restore.

O script recusa assumir uma manutenção já ativa. O servidor arbitra `enter` atomicamente e devolve um token de ownership, exigido no `leave`. `enter --timeout 60` que não drena falha, devolve o token para recuperação e mantém manutenção ligada para inspeção; não há resume automático desse estado duvidoso. Depois de uma janela drenada, o finally tenta retornar a origem mesmo se a cópia falhar. Uma falha ao sair é visível, não transformada em sucesso. O token da janela original está no manifesto privado do backup, pois também está no dump fechado; não publique esse manifesto integralmente.

O restore cria um namespace novo `pf-evidencedesk-restore-<id>`, banco e volumes vazios, sem portas publicadas e sem iniciar API/frontend/worker. Valida hashes e caminhos antes de escrever, recusa links/traversal e volumes com conteúdo. Mantém a origem em manutenção durante aquisição do ledger/checkpoint atuais e reconciliação no destino, eliminando a corrida com uma exclusão concorrente. Não usa o ledger antigo do backup. Identidade, sequência e hash do prefixo precisam prolongar o checkpoint do banco restaurado: cópia truncada/divergente não abre o destino. `reconcile-ledger` exige `--restore-mode` e token do dono. A aplicação do ledger e a conferência dos objetos referenciados são obrigatórias; o destino permanece fechado.

O resultado em `docs/evidence/restore-*.json` contém duração, identidade dos projetos e hashes do manifesto/ledger, sem conteúdos. Os containers de restauração são parados ao terminar e volumes permanecem para inspeção; identifique o namespace exato antes de removê-los. Não use prune. Restaurar sobre o ambiente principal não é um comando deste script.

O limite inicial de cópia é 50 mil arquivos/4 GiB e o ledger até 16 MiB. São proteção operacional explícita para o laboratório, não capacidade do PostgreSQL/Blob. Ao exceder, o comando falha; ampliar requer medir tempo/espaço e revisar a janela, não ocultar arquivos. Os 24 h de RPO são objetivo de agendamento; a idade real do backup e o watermark do ledger são informações separadas.

Ensaios necessários para aceitar operação: arquivo corrompido, objeto ausente, exclusão posterior ao backup, ledger ausente e restore completo. Testes unitários de arquivo não substituem os ensaios no banco real. Consulte as evidências datadas antes de afirmar que esses cenários passaram.

Fontes desta seção, conferidas em **22/09/2026**: [backup.py](../../scripts/backup.py) · [storage_snapshot.py](../../scripts/storage_snapshot.py) · [erasure-restore-20260921.json](../evidence/erasure-restore-20260921.json).

## Ensaios executados em 21/09/2026

O backup local criou uma cópia privada de 110 objetos referenciados em 6,735 s. A [restauração isolada aprovada](../evidence/restore-review0733.json) verificou 110 referências em 34,734 s, com ledger na sequência 0, destino fechado/parado e origem reaberta. Isso é um RTO de laboratório para aquela massa, não garantia de 10 min em produção. Não há agendamento diário implementado que comprove RPO de 24 h.

[A primeira tentativa](../evidence/restore-review0730.json) expôs um token de ownership começando com hífen: o argumento separado era confundido com opção pelo parser. A chamada agora usa `--token=valor`, possui regressão e não registra o token em erro. O sucesso só é escrito após saída da manutenção da origem e parada do destino. A falha foi preservada, sem substituir o histórico por sucesso.

A exclusão de duplicatas físicas, derivados e repetição após unlink parcial também foi exercitada em integrações PostgreSQL com banco descartável. O restore de 110 objetos tinha ledger vazio e antecedia a geração Azure; essa evidência histórica não inclui o resultado posterior. Cleanup durável e ownership de quota estão descritos no [runbook de retenção](retention.md).

O [ensaio físico posterior de exclusão](../evidence/erasure-restore-20260921.json) reutilizou somente o namespace de capacidade, com uma nova fonte Markdown sintética e um dossiê manual dependente. O backup continha 173 objetos e checkpoint 0. Depois do backup, a API administrativa publicou a exclusão e o worker concluiu o purge; o ledger independente avançou para 1. O restore em `pf-evidencedesk-restore-erasure0854` restaurou os bytes antigos e reaplicou esse ledger atual antes de permitir qualquer abertura.

A [restauração](../evidence/restore-erasure0854.json) concluiu em 29,141 s, com 172 referências remanescentes verificadas. O teste autenticado das rotas ASGI no destino fechado retornou 404 para fonte, arquivo original e dossiê; a inspeção do volume confirmou o arquivo ausente, texto canônico e alegações vazios e zero referência à chave apagada. Não foi iniciado servidor HTTP público no destino. A sequência 1 ficou reconciliada, origem e destino do ensaio foram parados e os volumes preservados. Nenhuma chamada de modelo ocorreu. Isso comprova o caminho completo para essa fonte e esse dossiê; duplicatas, unlink parcial e ledger divergente têm suas próprias integrações, não uma execução física combinada de todos os casos.

Para repetir em outro namespace de capacidade previamente preparado, use `python scripts/check_erasure_restore.py --project pf-evidencedesk-capacity-<id> --backup C:\caminho-protegido\backups\novo --target pf-evidencedesk-restore-<id> --output docs/evidence/erasure-<id>.json`. O helper exige o prefixo isolado, zero chamadas de provedor e destino/arquivo de evidência novos; importa apenas sua fonte sintética, preserva o restante do corpus e para os containers ao terminar. A execução inteira de 21/09 levou 58,890 s; isso inclui preparação e verificações, não apenas restore.

Fontes desta seção, conferidas em **22/09/2026**: [restore-review0733.json](../evidence/restore-review0733.json) · [restore-review0730.json](../evidence/restore-review0730.json) · [erasure-restore-20260921.json](../evidence/erasure-restore-20260921.json).

## Reabertura opcional conferida em 22/09/2026

Para preparar um ambiente sintético novo e executar a sequência completa, consulte os [pré-requisitos e o comando de reprodução](../restore-read-story.md#reprodução-e-dificuldades). O novo `scripts/prove_restore_read.py` constrói a associação fonte/imagem e congela também as entradas do seed. Seus controles foram testados no host; o percurso completo desse novo wrapper ainda não foi executado. O manifesto conserva os comandos efetivamente usados na prova abaixo.

A [prova com navegador](../restore-read-story.md) passou no destino `pf-evidencedesk-restore-edread-492911fe-r2`: ledger 0→1, uma exclusão reaplicada, 108 referências remanescentes, incidente sobrevivente legível e fonte/original/dossiê dependente com 404. A inspeção posterior confirmou objeto ausente e remoção das referências. Não houve chamada ao provedor. Tempos: operação restore 63,305 s incluindo abertura/leitura/fechamento; helper completo 86,072 s. Build/seed são separados; não converter esses tempos em objetivo comercial de RTO.

`backup.py verify-restore` continua fechado por padrão. O callback de leitura opcional só roda dentro da manutenção ainda pertencente ao executor, após ledger e objetos verificados. Ele identifica imagens e portas efetivas, abre API/frontend em loopback sem worker/modelos, faz login em sessão nova, percorre leituras e fecha o destino antes de devolver o controle. Um relatório de restore salvo não serve como comando de reabertura: o ledger pode ter avançado depois.

A API não é tornada somente leitura ao sair da manutenção. A prova limita o percurso e compara 17 tabelas de domínio, `provider_calls` e checkpoint; sessões/auditoria/controles têm mudanças legítimas explicitamente fora dessa igualdade. Os containers foram parados, com volumes preservados para inspeção. A prova não altera o procedimento para restaurar sobre um ambiente principal nem autoriza remover volumes compartilhados.

[Manifesto, fontes e capturas](../evidence/restore-read-story/20260922T072246Z-492911fe/manifest.json). A preparação falhada por `claim.id` em vez de `claim_id` foi preservada; somente a segunda tentativa é apresentada como aprovada. Tokens/backup/saídas brutas continuam privados, fora do repositório. Para perda do host ainda é necessário ensaiar cópia protegida e ledger em destino independente.

Fontes desta seção, conferidas em **22/09/2026**: [manifest.json](../evidence/restore-read-story/20260922T072246Z-492911fe/manifest.json).
