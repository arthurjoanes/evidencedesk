# Ambiente de desenvolvimento observado

Inspeção de 21/09/2026, aproximadamente 06:29 UTC. Leituras de recurso livre são um snapshot, não uma reserva para este projeto.

| Recurso | Observação |
|---|---|
| Host | Windows 11 Pro 10.0.26200; PowerShell |
| CPU | AMD Ryzen 7 5700X3D, 8 núcleos/16 threads |
| RAM | 31,89 GiB total; 4,47 GiB livres na primeira leitura |
| GPU | RTX 5070 Ti, 16.303 MiB; 2.144 MiB ocupados; driver 616.64 |
| GPU em Linux/container | Ainda não validada; a geração principal usa Azure |
| Disco C: | 403,59 GiB livres de 930,45 GiB |
| Disco D: | 35,77 GiB livres de 931,50 GiB |
| Docker | Desktop 4.89.0; Engine 29.7.2; Compose 5.5.0; contexto desktop-linux |
| WSL | WSL2, kernel 6.18.33.2; daemon com 16 CPUs e 15,56 GiB de RAM |
| Host Python | 3.11.9; scripts operacionais usam apenas biblioteca padrão |
| Host Node/npm/Git | 24.19.0 / 11.17.0 / 2.55.0.windows.5 |

As portas 3106, 8106, 5546, 8446, 3206, 9106, 9187, 9196 e 5106 estavam livres. A disponibilidade deve ser conferida novamente no start. Outros projetos estavam ativos; nenhum serviço, volume, imagem ou configuração deles foi alterado.

Python 3.12.14 é o runtime definido do backend, com imagem fixada por digest. O primeiro start confirmou PostgreSQL 17.11 (Debian 17.11-1.pgdg12+2) e pgvector 0.8.6. `ed_app` e `ed_owner` não têm SUPERUSER, CREATEDB, CREATEROLE ou BYPASSRLS; `ed_app` não é membro de `ed_owner`. Essas escolhas não afirmam disponibilidade da mesma extensão no serviço Azure futuro.

O núcleo limita banco a 512 MiB, API a 512 MiB, worker a 1.536 MiB e frontend a 512 MiB. São tetos iniciais, sujeitos a medição; modelos e builds podem demandar mais. Observabilidade, treino e carga não iniciam automaticamente. Builds frontend/modelos devem ser coordenados para não saturar o host.

Os bancos, modelos e artefatos privados ficam em volumes Docker próprios. A pasta sincronizada contém apenas fontes e artefatos pequenos permitidos. Não há garantia de backup do Docker apenas por usar OneDrive.

O perfil observability tem teto adicional aproximado de 1.376 MiB: collector 192, Prometheus/Loki/Tempo/Grafana 256 cada, Alertmanager 64, probe/receiver 48 cada. Tetos não equivalem a consumo observado nem garantem desempenho. A primeira validação executou somente comandos de configuração efêmeros e registrou [sete checks](evidence/infra-config-check.json); isso não comprova ingestão de traces, logs ou entrega de alertas.

## Evidências posteriores à inspeção inicial

O runtime final chegou à migração 0008; [readiness, UID efetivo 10001, ausência de capabilities, filesystem somente leitura e ausência de OOM](evidence/runtime-final.json) foram observados na imagem indicada nesse registro. [O resultado Azure anterior](evidence/azure-persistence-final.json) manteve os hashes do JSON e do manifesto privados após o restart; não houve nova geração nesse check.

A GPU em container foi posteriormente validada e o laboratório ML executou treino/retrieval próprios; os resultados detalhados estão nos artefatos de `experiments`. O serviço opcional `models` tem perfil `ml`, teto de 3 GiB/2 CPUs, cache somente leitura e nenhum endpoint externo. Não recebe credencial Azure ou URL de banco. Download de pesos e build de dependências são passos separados e explícitos; `HF_HUB_OFFLINE=1` impede download no start desse serviço.

O núcleo operacional e os scripts de backup usam biblioteca padrão; scripts de capacidade/observabilidade usam `httpx` do ambiente do backend. Terraform 1.16.3/AzureRM 5.6.0 foram usados somente para validação local, com cache posterior fora do OneDrive. Um cache inicial `.terraform` permanece ignorado no diretório de IaC; ele não contém state nem segredos de implantação.

[Capacidade](runbooks/capacity.md), [backup/restore](runbooks/backup-restore.md), [observabilidade](runbooks/observability.md) e [limites do perfil Azure hospedado](runbooks/azure-hosted.md) distinguem checks de configuração, execução real e objetivos ainda não comprovados. Os diretórios de dados do Docker não são protegidos automaticamente pela sincronização das fontes.
