# Projeto Fersouro — orientação para o Claude

Este repositório contém o **datalake** do Grupo Terrasul (arquitetura medalhão,
Python + DuckDB + Parquet, fonte Oracle Linx). Todo o projeto vive em
`datalake/`.

- Branch de trabalho: `claude/datalake-from-scratch-jkv3wq`.
- Visão geral e como operar o datalake: `datalake/README.md`.

## Estoque Mínimo de Peças

Sistema que compara o disponível real das peças (do ERP, via datalake) com uma
lista de mínimos e publica numa página local + planilha, com histórico diário e
atualização de hora em hora.

**Antes de mexer no Estoque Mínimo, leia `datalake/docs/estoque-minimo.md`** —
cobre a fonte do número, arquitetura, a lista de mínimos, a página, o servidor,
a automação, como atualizar o código, solução de problemas e as pendências
abertas (seção 11).

## Relatórios em Excel

Pastas de trabalho `.xlsx` com abas de resumo/detalhe, formatação, totais e
destaques, definidas em YAML (`datalake/conf/reports/*.yml`) e geradas ao fim de
cada carga. **Antes de mexer nos relatórios, leia
`datalake/docs/relatorios.md`.**

## RPA do Portal Rede VW

Robô Playwright que faz login no portalredevw.com.br e entra num usuário
específico. **Antes de mexer, leia `datalake/docs/rpa-portal-vw.md`.**

## RPA SAGA2 - VH47 (Garantia VW → planilha)

Navega no portal até a Lista de arquivos do SAGA2 - VH47, baixa só os PDFs
ainda não processados, extrai SG e valor total e faz upsert numa planilha
existente (`src/datalake/rpa/`, `conf/rpa/saga_vh47.yml`). **Antes de mexer,
leia `datalake/docs/saga-vh47.md`.**

**Auxiliar de Fechamento da Garantia:** antes de qualquer nova integração
(portal, Drive, e-mail, outros sistemas VW), leia
`datalake/docs/auxiliar-fechamento-mapa.md`. Ele traz o mapa de fontes,
acessos, credenciais e riscos, que precisa de validação do responsável. A
regra permanente é: leitura antes de escrita, evidência para cada dado e
INCONCLUSIVO em vez de suposição.

Roda no servidor da empresa em `C:\datalake`. Não é preciso "transferir" nada
entre sessões: o contexto está no código e nessa documentação.

**Papel do auxiliar:** assistente de garantia com foco em detalhe financeiro,
O.S., débitos e planilhas. Antes de entregar qualquer fechamento, siga o
"Padrão de entrega" e rode a auditoria de débitos (`rpa-saga/debitos.py`),
ambos em `datalake/docs/saga-vh47.md`. Os erros já cometidos e as regras que
saíram deles estão em "Lições aprendidas", no mesmo arquivo.
