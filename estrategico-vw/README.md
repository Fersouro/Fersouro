# Estratégico VW — Planilha Consolidada

Consolidação da planilha **Estratégico PAC VII** com preço estratégico (+40%) e
área de cruzamento com o extrato do DataLake.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `Estrategico_VW_Consolidado.xlsx` | Entregável principal (3 abas) |
| `Estrategico_VW_Consolidado.csv` | Mesma tabela em CSV (separador `;`, decimal `,`) |
| `gerar_consolidada.py` | Script que gera o xlsx a partir da planilha de origem |
| `Estrategico_PAC_VII_5.xlsx` | Planilha de origem enviada pelo usuário |

## Mapeamento da planilha de origem (aba `Pedido`)

- **Código da Peça** → coluna `C` (`Partnumber`)
- **Preço Base** → coluna `H` (`Preço Rev. c/ IPI (Promo.)`)
- 42 itens reais (linhas 5 a 46). As linhas 47–404 são preenchimento do
  formulário (partnumber = `0`) e foram descartadas.

## Abas do entregável

1. **Consolidado** — exatamente as 5 colunas solicitadas:
   `Código da Peça` · `Estoque (DataLake)` · `Preço Público (DataLake)` ·
   `Preço Original (Coluna H)` · `Preço Estratégico (+40%)`
2. **DataLake** — área de colagem do extrato (colunas B e C, células amarelas).
   Os 42 códigos já vêm preenchidos na coluna A.
3. **Instruções** — legenda de cores e o parâmetro de acréscimo (`B6 = 40%`).

## Cálculo

    Preço Estratégico = Preço Original (Coluna H) × (1 + Instruções!$B$6)

O acréscimo está em célula própria; alterá-lo recalcula toda a coluna E.

## Estoque e Preço Público

Não há conexão com o DataLake nesta sessão, portanto essas duas colunas ficam
com `Pendente` até que o extrato seja colado na aba `DataLake`. A busca é feita
por `INDEX`/`MATCH` usando o Código da Peça como chave:

- `Pendente` — código presente no extrato, mas sem valor informado
- `Não encontrado` — código ausente do extrato

## Regeneração

    python3 gerar_consolidada.py Estrategico_PAC_VII_5.xlsx Estrategico_VW_Consolidado.xlsx
