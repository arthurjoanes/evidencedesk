# Política de segurança

O EvidenceDesk é um laboratório de portfólio com dados sintéticos. Seu [modelo de ameaças](docs/threat-model.md) descreve os controles implementados e as condições que ainda precisam ser atendidas antes de uma exposição pública.

## Revisões e escopo

A versão atual da branch `main` é a referência para analisar relatos e desenvolver correções. Informe também o SHA da revisão afetada; relatórios, imagens e commits históricos conservam o escopo da execução original. Esta política não estabelece manutenção LTS, backports ou prazo garantido de resposta e correção.

O [perfil local](infra/compose/compose.yaml) publica serviços em loopback e inclui contas de demonstração. A exposição pública exige revisar identidade, TLS, rede, segredos e recuperação fora do host, conforme os [requisitos do perfil hospedado](docs/runbooks/azure-hosted.md).

## Relatar uma vulnerabilidade

Faça o primeiro contato privado com [Arthur Joanes pelo LinkedIn](https://www.linkedin.com/in/arthur-joanes-6a2967373/), usando o assunto **Segurança — EvidenceDesk**, para combinar um canal de envio dos detalhes. O contato também está no [README](README.md#autor-e-licença).

Prepare um relato com:

- SHA da revisão e componente afetado.
- Ambiente e condições necessárias para reproduzir o problema.
- Impacto observado, separado de hipóteses.
- Reprodução mínima com dados sintéticos e resultado esperado/obtido.

Não publique credenciais, dados pessoais, arquivos privados ou detalhes de exploração em uma issue pública. Remova esses dados de logs e capturas antes de compartilhá-los.

## Controles, evidências e limites

| Documento                                                        | O que consultar                                                                 |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| [Modelo de ameaças](docs/threat-model.md)                        | Autorização, isolamento, sessões, uploads, workers, IA e pendências de operação |
| [Segurança das imagens](docs/publication-security.md)            | Scans com imagem, data e base identificadas; cobertura de API e frontend        |
| [Carregamento de checkpoints ML](docs/ml-checkpoint-security.md) | Correção local específica e suas próprias verificações                          |
| [Backup e restauração](docs/runbooks/backup-restore.md)          | Procedimento operacional e limites de recuperação                               |
| [Workflow de CI](.github/workflows/ci.yaml)                      | Verificações automatizadas e seus escopos                                       |
| [Configuração do Gitleaks](.gitleaks.toml)                       | Regras padrão e exceções delimitadas para valores comprovados                   |

Um scan sem achados cobre a imagem e a base identificadas naquele relatório; não demonstra ausência universal de vulnerabilidades. O gate de API/frontend não cobre automaticamente ML, PostgreSQL ou observabilidade. Os testes e o backport de ML têm registros próprios. Esta política não constitui auditoria profissional ou certificação de produção.

A localização deste arquivo segue a [documentação oficial de políticas de segurança do GitHub](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/add-security-policy).
