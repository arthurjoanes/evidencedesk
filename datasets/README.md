# Dados sintéticos do EvidenceDesk

`python scripts/ops.py seed` gera estes arquivos quando estão ausentes. Para gerar os pacotes separadamente, use o comando abaixo.

A massa é autoral e fictícia. Não contém dados de clientes, informações do empregador ou texto copiado de postmortems. Execute na raiz:

```powershell
python datasets/generate.py --output datasets/generated
```

O padrão gera 30 incidentes, 90 documentos e aproximadamente 20 mil observações. Há seis pacotes independentes, três por tenant, com 18 arquivos importáveis cada. O limite por pacote permanece 40 entradas/40 MiB; nenhum arquivo excede 10 MiB. `index.json` e `incidents.json` ajudam o seed administrativo; não são evidências nem entradas do manifesto.

Cada linha de events.jsonl segue `EventInput` em reconciliation/contracts.py. A API atribui tenant, evidence_id, ingested_at, hash do arquivo e número da linha. `occurred_at` e `observed_at` permanecem nulos quando desconhecidos. Mapeamentos explícitos em mappings.jsonl relacionam source_system + source_order_reference ao order_reference canônico.

Snapshots CSV usam exatamente: source_system,snapshot_id,order_reference,status,as_of,source_timezone. A API acrescenta provenance; as_of nunca é substituído pela data do upload. JSONL não aceita campos desconhecidos. Payload limitado a 16 KiB.

Coverage registra from/to, fonte, complete/partial/unknown, gaps, tipos observados e clock_uncertainty_ms. Precisão ausente não significa relógio perfeito. Uma janela incompleta pode ser publicada, mas não provar falta de transição.

Os nomes de pedido são repetidos entre organizações de propósito. Acesso é decidido pelo tenant autenticado, nunca pelo ID ou source_tenant do arquivo. O seed deve carregar cada pacote no tenant correspondente e validar o manifesto como qualquer importação. Source_tenant é uma declaração verificável, não autoridade.

As dez famílias incluem reentrega, atraso, ordem de recepção diferente da ocorrência, timeout com aceite incerto, expiração, snapshot antigo, identificação ausente, procedimento obsoleto, falha parcial e falta de coleta. Os dados incluem casos normais para comparação. Variações são sintéticas: não sustentam alegações de ganho em produção.

Não importe `evals/` ou `experiments/` no corpus. Golds, rótulos e casos reservados ficam fora do índice da demo.

