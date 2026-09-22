# EvidenceDesk

Investigação de incidentes de pedidos com evidências, IA e revisão humana.

O pagamento foi confirmado, mas o pedido continua pendente. O EvidenceDesk reúne eventos, snapshots e procedimentos para conferir o que aconteceu, registrar uma hipótese com fontes e submetê-la a outro analista. A conciliação calcula as divergências; a IA ajuda a redigir a investigação.

![Bancada de investigação com leitor de evidências](docs/images/workspace-desktop.png)

## Uma investigação do início ao fim

1. Importe um pacote de eventos, documentos e snapshots.
2. Abra o incidente e confira divergências, linha do tempo e cobertura das fontes.
3. Escreva um dossiê ou solicite um rascunho à IA, com referências verificáveis.
4. Submeta uma revisão. Outra pessoa compara as alegações e registra a decisão.
5. Exporte a revisão aprovada com suas fontes e os dados da decisão.

O fluxo manual funciona sem conta Azure. A geração é opcional e produz rascunhos sujeitos à revisão.

Dois exemplos distinguem o trabalho feito: um pagamento anterior a um snapshot ainda pendente pode gerar uma divergência; duas entregas do mesmo evento lógico contam como duas observações, não como dois pagamentos. A conclusão conserva o recorte, a cobertura e as fontes usadas. O [guia de problemas, exemplos e decisões](docs/problem-solution.md) liga esses casos às regras e aos testes, incluindo permissões revogadas, edição concorrente, custo incerto de IA e retenção.

## Arquitetura e escolhas

```mermaid
flowchart LR
    UI[Next.js · bancada] --> API[FastAPI · regras e autorização]
    API --> DB[(PostgreSQL · dados e fila)]
    API --> Files[Arquivos privados]
    Worker[Worker Python] <--> DB
    Worker --> Files
    Worker --> Azure[Azure OpenAI · opcional]
    Worker --> Models[Embeddings e reranker · opcionais]
```

- **Monólito modular, API e worker separados.** As regras ficam em módulos por responsabilidade. Trabalhos demorados saem da requisição HTTP; a fila usa o mesmo PostgreSQL, com lease e fencing para impedir publicação por um worker que perdeu o job.
- **Autorização no backend.** RLS separa organizações; permissões de coleção e incidente limitam cada leitura, inclusive as fontes de resultados derivados. O modelo recebe apenas o contexto autorizado.
- **Evidências e revisões imutáveis.** Um snapshot fixa as fontes da investigação. Editar o dossiê cria outra revisão; a aprovação pertence à versão conferida e exige outro usuário.
- **Conciliação separada da geração.** Regras determinísticas calculam divergências. O modelo sintetiza fontes com orçamento limitado. Um resultado externo incerto exige tratamento explícito para evitar repetir uma chamada cobrada.

O armazenamento local compartilhado simplifica a instalação em um host. Operação entre hosts exige persistência remota e recuperação próprias. Veja os [contratos, alternativas e limites da arquitetura](docs/architecture.md).

## Rodar localmente

Requisitos: **Docker com Linux containers, Compose 2.24.4+ e Python 3.11+**. Na raiz do repositório:

```powershell
python scripts/ops.py config
python scripts/ops.py build
python scripts/ops.py start
python scripts/ops.py seed
```

O primeiro `seed` gera a massa sintética e carrega a demonstração. Abra [localhost:3106](http://127.0.0.1:3106). Entre como `ana@aurora.demo` para investigar ou `bruno@aurora.demo` para revisar. A senha de demonstração é `EvidenceDesk-demo-2026!`.

As contas e os dados são fictícios; os serviços são publicados apenas em loopback. `python scripts/ops.py stop` encerra o projeto preservando os volumes. [Configuração, Azure opcional e solução de problemas](docs/runbooks/local.md).

## Verificar e explorar

Os testes exercitam isolamento entre organizações, permissões de fontes, concorrência, perda de lease, edição de revisões, retenção e restauração. As jornadas no navegador incluem importação, leitura, aprovação e exportação. A [verificação da versão](docs/publication.md) registra os comandos, resultados e limites.

```powershell
python scripts/check_repository_docs.py
```

A [história de revisão e recuperação](docs/restore-read-story.md) reúne capturas de aprovação com fonte, conflito que preserva rascunho e reabertura após exclusão. Na execução local de 22/09, o destino manteve a fonte/original/dossiê excluídos inacessíveis, conferiu 108 referências remanescentes e fez zero chamadas ao provedor. A aprovação por contas distintas foi automatizada; não é avaliação humana da qualidade.

Para a suíte completa, veja o [guia de desenvolvimento e testes](docs/development.md). Para apresentar o produto, siga a [demonstração de cinco minutos](docs/demo.md).

## IA e escopo

A integração com Azure OpenAI já foi exercitada com uma geração real e reabertura do resultado após reinício. Embeddings, reranker e um experimento supervisionado usam dados sintéticos; seus [resultados e protocolo](experiments/README.md) estão versionados. O candidato treinado permanece separado do modelo ativo até cumprir os critérios de avaliação.

Citações estruturadas permitem conferir uma resposta, mas a qualidade semântica ainda exige avaliação humana. O [pacote preparado para revisão](evals/human-review/README.md) reúne 60 casos sintéticos de desenvolvimento em oito famílias, rubrica e formulários. Ainda não houve participantes ou adjudicação nesse pacote; o conjunto reservado não foi aberto. A aplicação completa roda localmente; a infraestrutura Azure é um perfil em desenvolvimento. O [model card](docs/model-card.md) e a [avaliação de segurança](docs/publication-security.md) detalham essas condições.

O perfil opcional de ML aplica uma [correção verificável no carregamento de checkpoints](docs/ml-checkpoint-security.md): shards devem ser arquivos regulares dentro da pasta do checkpoint. O build executa 15 regressões locais; isso não substitui a avaliação de segurança das demais dependências da imagem.

Python · FastAPI · PostgreSQL/pgvector · Next.js · TypeScript · Docker. [Licença MIT](LICENSE).
