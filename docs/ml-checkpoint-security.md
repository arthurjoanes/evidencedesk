# Carregamento de checkpoints ML

Fontes upstream conferidas em **22/09/2026**: [advisory GHSA-4j2p-28q2-5m79](https://github.com/advisories/GHSA-4j2p-28q2-5m79) e [loader da tag 1.15.0](https://github.com/huggingface/accelerate/blob/v1.15.0/src/accelerate/utils/modeling.py). O advisory lista versões até 1.14.0 e não informa versão corrigida; a observação sobre 1.15.0 vem da leitura do código daquela tag, não de uma ampliação silenciosa da faixa do advisory.

Em 22/09/2026 UTC, a imagem opcional de ML recebeu o backport local `evidencedesk-accelerate-shards-v1` para o loader de checkpoints fragmentados do Accelerate 1.13.0. O [relatório](../experiments/reports/checkpoint-security.json) identifica a imagem, os hashes e os testes. API e frontend não instalam esse ambiente ML.

Fontes desta seção, conferidas em **22/09/2026**: [checkpoint-security.json](../experiments/reports/checkpoint-security.json).

## Problema e correção

O [advisory CVE-2026-69112](https://github.com/advisories/GHSA-4j2p-28q2-5m79) descreve nomes de shards controlados pelo índice JSON que podem escapar da pasta do checkpoint ou apontar para arquivos especiais. A versão 1.15.0 foi consultada, mas seu [loader publicado](https://github.com/huggingface/accelerate/blob/v1.15.0/src/accelerate/utils/modeling.py) ainda construía caminhos com `os.path.join` sem essas verificações. Ausência de alerta em um catálogo para uma versão nova não comprova correção.

O [script do backport](../experiments/patch_accelerate.py) exige a versão e o SHA-256 exatos da fonte original, e falha se o trecho esperado mudar. Antes de carregar pesos, ele valida o índice como arquivo regular de até 16 MiB, exige um mapa não vazio de nomes e resolve cada caminho. Shards precisam permanecer dentro da pasta do checkpoint e ser arquivos regulares. Caminhos absolutos, escapes por `..`, links externos, diretórios, arquivos ausentes e FIFOs são recusados. Subpastas, links internos e checkpoints sem fragmentação continuam funcionando.

O build mantém os metadados de Accelerate 1.13.0 e registra o hash da fonte modificada em `/opt/evidencedesk/accelerate-patch.json`. `--check` confere o manifesto e o código instalado. O [verificador de ambiente](../experiments/verify_environment.py) exige essa verificação antes de comparar os 116 pacotes com o lock. Não há exclusão do CVE nem alteração de versão para silenciar scanners.

Fontes desta seção, conferidas em **22/09/2026**: [patch_accelerate.py](../experiments/patch_accelerate.py) · [verify_environment.py](../experiments/verify_environment.py).

## Reproduzir

Na raiz do repositório, com Docker Linux:

```sh
docker build -f experiments/Dockerfile -t pf-evidencedesk-ml:torch2.14-cu130-shards-v1 experiments
docker run --rm --network none --memory 1g --cpus 1 --user 10001 --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges pf-evidencedesk-ml:torch2.14-cu130-shards-v1 python /opt/evidencedesk/test_checkpoint_security.py
docker run --rm --network none pf-evidencedesk-ml:torch2.14-cu130-shards-v1 python /opt/evidencedesk/patch_accelerate.py --check
```

O Dockerfile aplica e verifica o patch e executa os 15 testes durante o build. O ensaio também foi repetido sem rede, com UID 10001, raiz somente leitura e tensor sintético de 2 × 2 em CPU. Nenhum modelo foi baixado, nenhum treino foi executado e nenhuma API paga foi chamada. O CI principal não constrói a imagem ML opcional; a evidência deste backport é uma execução local identificada, não um resultado remoto de CI nem novo benchmark.

O rebuild final usa arquivos LF, iguais aos bytes publicados pelo Git. As versões
do lock permanecem iguais; seu hash publicado é
`2d994242fbab69e83dcc980dc6f4ae5f54ce91ed5ba890452886b7c5140fe766`.
O histórico de build com lock CRLF conserva sua identidade e suas medições
originais. O índice atual foi conferido contra os arquivos publicados, sem
reescrever os resultados históricos para aparentar uma nova execução.

Fontes desta seção, conferidas em **22/09/2026**: [patch_accelerate.py](../experiments/patch_accelerate.py) · [test_checkpoint_security.py](../experiments/test_checkpoint_security.py) · [checkpoint-security.json](../experiments/reports/checkpoint-security.json).

## Compatibilidade e manutenção

Checkpoints fragmentados que usam links para blobs fora da própria pasta precisam ser materializados por cópia antes da carga. Esse contrato é deliberadamente mais restrito que o cache genérico do Hugging Face. O loader de checkpoints não fragmentados permanece inalterado. O diretório de pesos deve ser confiável e somente leitura durante a carga: a validação não promete proteção contra um processo local que substitua arquivos concorrentemente.

O patch cobre esse fluxo específico. Ele não atesta ausência de vulnerabilidades nas demais bibliotecas, desserialização de formatos não aprovados ou qualidade dos modelos. Scanners por versão podem continuar apontando o advisory; a evidência do backport deve acompanhar a triagem. Ao atualizar Accelerate, revisar a correção upstream, reaplicar ou remover conscientemente o patch e repetir os testes. Os resultados históricos de treino e a decisão humana de promoção permanecem separados.

Fontes desta seção, conferidas em **22/09/2026**: [patch_accelerate.py](../experiments/patch_accelerate.py) · [test_checkpoint_security.py](../experiments/test_checkpoint_security.py) · [checkpoint-security.json](../experiments/reports/checkpoint-security.json).
