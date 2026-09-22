# Padrão de documentação

Padrão editorial dos seis projetos do portfólio. O README apresenta o projeto; os guias detalham reprodução, contratos, decisões e evidências. O [registro de fontes e afirmações](fontes-e-afirmacoes.md) reúne as referências detalhadas deste repositório.

## Ordem de leitura

| Seção do README          | Pergunta que deve responder                                              |
| ------------------------ | ------------------------------------------------------------------------ |
| Visão geral              | Que problema resolve, para quem e em qual cenário?                       |
| Demonstração             | Como a aplicação se apresenta e qual jornada pode ser conferida?         |
| Arquitetura              | Como os componentes se conectam e onde ficam as responsabilidades?       |
| Stack e decisões         | Quais tecnologias foram usadas e que escolhas exigem explicação?         |
| Executar localmente      | Quais pré-requisitos, comandos e endereço permitem reproduzir o projeto? |
| Verificação e evidências | Como testar e quais resultados possuem prova reproduzível?               |
| Limites e segurança      | Quais restrições, riscos e condições de uso permanecem?                  |
| Documentação             | Qual guia abrir para cada aprofundamento?                                |
| Autor e licença          | Quem desenvolveu, como entrar em contato e qual licença se aplica?       |

Essa ordem é uma decisão editorial para leitura de portfólio: entender o problema e ver a aplicação antecedem os detalhes de execução. Os títulos são iguais nos seis projetos; o conteúdo e o diagrama representam cada implementação.

## Apresentação e navegação

O cabeçalho usa badges clicáveis de navegação: azul para demonstração, roxo para arquitetura, verde para execução, ocre para evidências e azul do LinkedIn para contato. Os rótulos identificam o destino sem depender da cor. Os SVGs são locais e não declaram aprovação de testes ou métricas automáticas.

O diagrama de arquitetura fica no próprio README, acompanhado de uma explicação e de links para a implementação. A [documentação do GitHub](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams) explica a renderização de Mermaid.

Capturas devem mostrar um estado real e um recorte legível, com data e contexto. O README privilegia a página principal e a ação explicada. Imagens muito altas ficam como links para consulta; a documentação não deve reduzir uma página inteira até tornar o texto ilegível. Uma imagem de interface demonstra apresentação, enquanto resultados de cálculo, isolamento ou persistência precisam de fonte própria.

<a id="afirmações-fontes-e-datas"></a>

## Referências e evidências

Priorize uma leitura fluida. Inclua referências quando ajudam a reproduzir um resultado, consultar uma decisão ou avaliar uma alegação relevante. Não é necessário anexar fonte e data a cada frase. Links úteis podem entrar na própria prosa; as referências detalhadas ficam no guia correspondente ou no registro central.

| Informação                                    | Referência útil                                | Contexto que deve permanecer                                                                          |
| --------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Comportamento, limite ou versão fixada        | Código, configuração ou guia técnico           | Link quando ajudar a entender ou reproduzir o comportamento; sem carimbo de conferência em cada seção |
| Resultado de teste, desempenho ou experimento | Artefato original, comando, cenário e ambiente | Data real da execução, revisão, amostra e condições                                                   |
| Valor de uma demonstração sintética           | Fixture, gerador ou resultado registrado       | Identificação do cenário e distinção de valores de mercado                                            |
| Preço de serviço externo                      | Página ou API oficial                          | Data da cotação, moeda, região, modalidade e unidade; distinguir estimativa de cobrança               |
| Compatibilidade ou correção de segurança      | Documentação oficial, release ou advisory      | Versões e alcance; data quando necessária para situar a informação                                    |
| Escolha de projeto ou procedimento            | Explicação da decisão e guia correspondente    | Apresentar como escolha ou instrução, sem exigir uma referência para toda decisão autoral             |

Evite repetir avisos de revisão documental ao longo do texto. Quando útil, registre a data da revisão uma única vez no documento central. Datas de capturas, testes, incidentes e preços permanecem junto ao resultado que identificam.

Corrija ou qualifique afirmações sem sustentação. Prefira fontes primárias para dados externos e resultados verificáveis. Consultar um relatório hoje não muda a data de sua execução. Artefatos históricos e protocolos vinculados por hash conservam os bytes originais; correções editoriais ficam nos documentos vivos.

## Código e manutenção

Blocos de código precisam declarar a linguagem correta, como `python`, `json`, `sql`, `yaml`, `sh` ou `powershell`. Campos e comandos curtos usam código em linha. A linguagem declarada habilita o realce do renderizador; as cores variam conforme o tema e os tokens presentes. Veja o [guia de realce do GitHub](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-and-highlighting-code-blocks).

Ao editar, confira os links relativos, as âncoras, a leitura no celular, os exemplos e a procedência das imagens. Preserve destinos existentes quando reorganizar títulos. Atualize o registro de fontes quando uma alteração mudar uma afirmação, uma tarifa, uma versão ou um resultado. O GitHub descreve propósito, uso e caminhos relativos no [guia de READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes).

## Referências de apresentação

A amostra principal contém os **oito primeiros resultados por estrelas** retornados pela [API de pesquisa de repositórios do GitHub](https://api.github.com/search/repositories?q=stars%3A%3E100000&sort=stars&order=desc&per_page=15), em **22/09/2026 às 19:23 UTC**, com `incomplete_results=false`. A consulta usa o corte de 100.000 estrelas e ordenação decrescente. O [snapshot da consulta](references/readme-study-20260922.json) conserva os números desse instante. As observações de apresentação abaixo são uma análise editorial dos READMEs consultados naquela data.

| Posição | Repositório                                                                         | Estrelas na consulta | Elemento aproveitado                                            |
| ------- | ----------------------------------------------------------------------------------- | -------------------: | --------------------------------------------------------------- |
| 1       | [Build Your Own X](https://github.com/codecrafters-io/build-your-own-x)             |              548.801 | Propósito curto e índice direto para o conteúdo.                |
| 2       | [Awesome](https://github.com/sindresorhus/awesome)                                  |              508.964 | Navegação por assuntos e caminhos de contribuição separados.    |
| 3       | [public-apis](https://github.com/public-apis/public-apis)                           |              482.304 | Índice e tabelas com colunas estáveis.                          |
| 4       | [freeCodeCamp](https://github.com/freeCodeCamp/freeCodeCamp)                        |              455.975 | Identidade, badges úteis, propósito e sumário.                  |
| 5       | [Free Programming Books](https://github.com/EbookFoundation/free-programming-books) |              397.453 | Recursos agrupados e licença fácil de encontrar.                |
| 6       | [OpenClaw](https://github.com/openclaw/openclaw)                                    |              390.259 | Início rápido, composição do sistema, segurança e documentação. |
| 7       | [System Design Primer](https://github.com/donnemartin/system-design-primer)         |              371.295 | Diagramas, decisões técnicas e fontes próximas ao assunto.      |
| 8       | [Developer Roadmap](https://github.com/nilbuild/developer-roadmap)                  |              367.912 | Atalhos no cabeçalho e estrutura do repositório.                |

O [Laya](https://github.com/NandhaKishorM/laya) foi a referência visual adicional indicada pelo autor. Seus badges e a separação entre exemplos, resultados e limites inspiraram a apresentação. Seus números de desempenho, preços e alegações não são evidência sobre estes projetos.

As referências orientaram escolhas de navegação e hierarquia. Não foram copiados slogans, resultados, logotipos de projetos ou declarações de qualidade. A seleção por estrelas registra popularidade observada naquele momento; as escolhas de documentação foram avaliadas pelo que ajudam o leitor a encontrar.
