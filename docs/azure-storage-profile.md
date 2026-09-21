# Preparação de armazenamento Azure

`backend/src/evidencedesk/evidence/azure_blob.py` implementa escrita imutável por chave, comparação dos bytes reais, leitura até10MiB, exclusão idempotente e paginação de prefixo por SDK. Quatro operações concorrentes por processo, paralelismo de transferência1, retries desativados e timeouts explícitos mantêm a responsabilidade de retry no chamador. Timeout do SDK/serviço não é uma transação distribuída nem prova de que o servidor não gravou o objeto.

O construtor hospedado usa ManagedIdentityCredential e forma o host HTTPS a partir de um nome de conta validado. Não recebe URL arbitrária, connection string/SAS do modelo ou nome de arquivo do navegador como autoridade. Não cria conta/container nem altera RBAC. O papel da identidade e a rede precisam ser configurados no plano de infraestrutura.

As dez verificações de contrato usam um double explícito do SDK: corrida de duas escritas, repetição, bytes diferentes, limite, chave inválida, exclusão repetida e erro sanitizado. Isso **não** demonstra comunicação real com Blob nem identidade no Azure. O core usa `PrivateStorage`; não há variável escondida habilitando este adaptador em produção.

Antes de selecioná-lo como storage do core, implementar/validar:

1. Reserva de I/O e quarentena duráveis para PUT remoto. Não manter lock/conexão DB enquanto aguarda rede; também não liberar quota enquanto uma escrita tardia ainda puder produzir bytes.
2. Limpeza com claim persistido, verificação de referência e publicação de conclusão protegida por fencing. A versão local usa remoção curta sob lock; trocar o método por rede sem alterar o protocolo seria incorreto.
3. Ledger de exclusões cloud independente do backup, identidade mínima e restore fechado até validar watermark/replay. O diretório local não pode morar em disco efêmero ACA.
4. Backup/restauração entre hosts, versões/soft-delete/lifecycle e objetivo de retenção acordado; excluir uma versão corrente não significa eliminar cópias anteriores do serviço.
5. Teste real de Managed Identity/RBAC, falhas de rede e Azure Monitor sem conteúdo sensível.

Fontes oficiais consultadas: [upload e autorização](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload-python), [contrato BlobClient](https://learn.microsoft.com/python/api/azure-storage-blob/azure.storage.blob.blobclient) e [limites/transferência em blocos](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blobs-tune-upload-download-python). O caminho local com inferência Azure já executada não depende desse rollout.
