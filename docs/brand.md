<a id="identidade-visual-do-evidencedesk"></a>

# Tipografia e acessibilidade do EvidenceDesk

Cada estado tem rótulo ou mensagem: a cor sozinha não indica aprovação, falha ou falta de evidência. O foco e os limites necessários dos controles precisam permanecer visíveis; divisórias podem ser mais discretas que campos interativos.

IBM Plex Sans permanece na aplicação, com IBM Plex Mono em identificadores e JSON. O HTML offline conserva Segoe UI/Cambria, sem baixar fontes. Títulos, citações e controles têm a hierarquia da tarefa; uma apresentação visual não substitui fonte, autorização ou julgamento.

<a id="contraste-dos-tokens"></a>

## Contraste na interface

Razões calculadas pela luminância relativa sRGB do WCAG. Elas descrevem estas combinações, sem certificar todas as páginas e estados.

| Combinação                     | Contraste |
| ------------------------------ | --------: |
| Texto da ação principal        |    8,16:1 |
| Texto principal sobre branco   |   14,38:1 |
| Texto secundário sobre o fundo |    5,66:1 |
| Link sobre área selecionada    |    7,25:1 |
| Foco sobre branco              |    4,97:1 |
| Limite de controle sobre o fundo |  3,55:1 |

Use os testes de navegador descritos no [guia do frontend](frontend.md) ao alterar cores, foco ou layout. [WCAG 2.2](https://www.w3.org/WAI/WCAG22/quickref/) orienta contraste de texto e componentes, além de foco e reflow.
