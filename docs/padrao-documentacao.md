# Padrão de documentação

Padrão editorial adotado em **22/09/2026** para os seis projetos do portfólio. O README apresenta o projeto; os guias detalham reprodução, contratos, decisões e evidências. O [registro de fontes e afirmações](fontes-e-afirmacoes.md) documenta a conferência específica deste repositório.

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

O diagrama de arquitetura fica no próprio README, acompanhado de uma explicação e de links para a implementação. Diagramas Mermaid podem ser renderizados em arquivos Markdown do GitHub. Fonte: [documentação oficial de diagramas](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams), consultada em **22/09/2026**.

Capturas devem mostrar um estado real e um recorte legível, com data e contexto. O README privilegia a página principal e a ação explicada. Imagens muito altas ficam como links para consulta; a documentação não deve reduzir uma página inteira até tornar o texto ilegível. Uma imagem de interface demonstra apresentação, enquanto resultados de cálculo, isolamento ou persistência precisam de fonte própria.

## Afirmações, fontes e datas

Cada afirmação verificável deve ter uma fonte ligada ao trecho ou à seção correspondente, com a data adequada. A revisão usa as seguintes classes:

| Tipo de informação                                          | Fonte necessária                                                                 | Data e limites a registrar                                                                                                    |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Comportamento implementado, limite ou versão fixada         | Código, configuração ou arquivo de dependências; teste relacionado quando houver | Data da inspeção e revisão analisada. Inspeção não implica execução do teste.                                                 |
| Resultado de teste, desempenho ou experimento               | Artefato original, comando, cenário e ambiente                                   | Data real da execução, amostra e condições. Um resultado antigo permanece histórico.                                          |
| Valor de uma demonstração sintética                         | Fixture, gerador, consulta ou resultado registrado                               | Data da prova e identificação do cenário; distinguir de valores de mercado.                                                   |
| Preço de serviço externo                                    | Página ou API oficial do fornecedor                                              | Data da consulta, moeda, região, modalidade, unidade e condições. Distinguir tarifa, estimativa calculada e cobrança efetiva. |
| Compatibilidade, correção de segurança ou requisito externo | Documentação oficial, release ou advisory específico                             | Data da consulta, versões afetadas e alcance da afirmação.                                                                    |
| Escolha de projeto ou procedimento                          | Decisão explícita e arquivos aos quais se aplica                                 | Data da revisão; apresentar como escolha ou instrução, sem transformá-la em resultado medido.                                 |

Afirmações sem sustentação devem ser corrigidas, retiradas ou identificadas como hipótese ou pendência. Uma fonte que reproduz a própria alegação não basta. Fontes primárias têm preferência; quando a página atual divergir de um snapshot antigo, registrar as duas épocas e o motivo da diferença.

As datas de **execução**, **publicação da fonte** e **consulta** têm significados diferentes. Consultar um relatório hoje não atualiza a data de seus resultados. Artefatos históricos e protocolos vinculados por hash conservam os bytes originais; correções editoriais ficam nos documentos vivos e apontam a versão anterior.

## Código e manutenção

Blocos de código precisam declarar a linguagem correta, como `python`, `json`, `sql`, `yaml`, `sh` ou `powershell`. Campos e comandos curtos usam código em linha. A linguagem declarada habilita o realce do renderizador; as cores variam conforme o tema e os tokens presentes. Fonte: [documentação oficial de realce](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-and-highlighting-code-blocks), consultada em **22/09/2026**.

Ao editar, confira os links relativos, as âncoras, a leitura no celular, os exemplos e a procedência das imagens. Preserve destinos existentes quando reorganizar títulos. Atualize o registro de fontes quando uma alteração mudar uma afirmação, uma tarifa, uma versão ou um resultado. O GitHub descreve propósito, uso e caminhos relativos no [guia de READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes), consultado em **22/09/2026**.

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

O [Laya](https://github.com/NandhaKishorM/laya), indicado como referência visual, também foi consultado em **22/09/2026**. Seus badges e a separação entre exemplos, resultados e limites inspiraram a apresentação. Seus números de desempenho, preços e alegações não são evidência sobre estes projetos.

As referências orientaram escolhas de navegação e hierarquia. Não foram copiados slogans, resultados, logotipos de projetos ou declarações de qualidade. A seleção por estrelas registra popularidade observada naquele momento; as escolhas de documentação foram avaliadas pelo que ajudam o leitor a encontrar.
