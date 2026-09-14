# Projeto Fersouro — orientação para o Claude

Este repositório contém o **datalake** do Grupo Terrasul (arquitetura medalhão,
Python + DuckDB + Parquet, fonte Oracle Linx). Todo o projeto vive em
`datalake/`.

- Branch de trabalho: `claude/datalake-from-scratch-jkv3wq`.
- Visão geral e como operar o datalake: `datalake/README.md`.

## Estoque Mínimo de Peças

Sistema que compara o disponível real das peças (do ERP, via datalake) com uma
lista de mínimos e publica numa página local + planilha, com histórico diário e
atualização 6×/dia.

**Antes de mexer no Estoque Mínimo, leia `datalake/docs/estoque-minimo.md`** —
cobre a fonte do número, arquitetura, a lista de mínimos, a página, o servidor,
a automação, como atualizar o código, solução de problemas e as pendências
abertas (seção 11).

## Relatórios em Excel

Pastas de trabalho `.xlsx` com abas de resumo/detalhe, formatação, totais e
destaques, definidas em YAML (`datalake/conf/reports/*.yml`) e geradas ao fim de
cada carga. **Antes de mexer nos relatórios, leia
`datalake/docs/relatorios.md`.**

Roda no servidor da empresa em `C:\datalake`. Não é preciso "transferir" nada
entre sessões: o contexto está no código e nessa documentação.
