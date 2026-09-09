# Relatórios em Excel — documentação

Um **relatório** é uma pasta de trabalho `.xlsx` com várias abas, número
formatado como número se lê (R$, %, dd/mm/aaaa), linha de total e destaque no
que precisa de atenção. Cada relatório é um arquivo YAML em
`datalake/conf/reports/`.

> Não confundir com o **export** (`datalake export`): aquele grava um modelo
> gold por arquivo, cru, para quem vai levar o dado para outro lugar. O
> relatório é para ser lido por uma pessoa.

---

## 1. Como rodar

```bash
datalake report                 # todos os relatórios
datalake report -r margem_pecas # só um (pode repetir o -r)
datalake report --list          # o que existe, sem gerar nada
datalake report --out D:\saida  # outra pasta de destino
```

Os arquivos saem em `<lake>/export/relatorios/` — no servidor,
`C:\datalake\export\relatorios\`. Como o servidor da página publica a pasta
`export` inteira, eles já ficam acessíveis na rede em
**`http://IP-DO-SERVIDOR:8080/relatorios/`**.

O `datalake run` gera os relatórios sozinho, no fim do pipeline (depois do
export). Ou seja: as 6 cargas diárias já atualizam as planilhas. Para desligar,
`settings.yml`:

```yaml
reports:
  enabled: false
```

---

## 2. Como definir um relatório

Um arquivo por relatório em `conf/reports/`. O prefixo numérico do nome do
arquivo só serve para ordenar a listagem — o nome do relatório é o campo
`name`, e é ele que vira `nome.xlsx`.

```yaml
name: margem_pecas                # vira margem_pecas.xlsx
title: Margem de Peças            # título na capa
description: Venda, custo e lucro por filial, líquidos de devolução.

formats:                          # vale para todas as abas
  lucro_porcentagem: percentual
  venda_total: moeda

sheets:
  - name: Mes atual               # nome da aba (o Excel corta em 31 caracteres)
    description: O que a aba mostra — aparece na capa.
    sql: |
      SELECT filial, venda_total, lucro
        FROM margem_pecas
       WHERE competencia = date_trunc('month', current_date)
       ORDER BY lucro DESC
    totals: [venda_total, lucro]  # linha TOTAL no fim
    formats:                      # só desta aba; vence o de cima
      lucro: moeda
    highlights:
      - when: lucro < 0           # expressão SQL sobre o resultado da aba
        style: vermelho           # vermelho | amarelo | verde | azul
        scope: row                # 'row' (padrão) ou o nome de uma coluna
    limit: 50000                  # opcional

  - name: Detalhe
    model: margem_pecas           # atalho para SELECT * FROM margem_pecas
```

`sql` e `model` são exclusivos: ou um, ou outro.

### O que o SQL enxerga

As mesmas views da camada gold:

- `<fonte>__<tabela>` para toda tabela da silver (ex.: `ccm__pec_item_revenda`);
- `<tabela>` quando o nome não se repete entre as fontes;
- o nome de cada **modelo gold** materializado (ex.: `margem_pecas`).

É SQL do DuckDB, igual ao dos modelos gold — não há linguagem nova.

---

## 3. Formatos

Formato nomeado ou máscara do Excel crua (`'#,##0.000'` etc.).

| Nome | Mostra | Quando usar |
|---|---|---|
| `moeda` | `R$ 1.234,56` | valor em dinheiro |
| `numero` | `1.234,56` | quantidade fracionária |
| `inteiro` | `1.234` | contagem |
| `percentual` | `12,50%` | valor **já** multiplicado por 100 (o que a gold entrega) |
| `fracao` | `12,5%` | valor entre 0 e 1 (o Excel multiplica) |
| `data` | `13/08/2026` | data |
| `data_hora` | `13/08/2026 09:30` | data com hora |
| `mes` | `08/2026` | competência |
| `texto` | como está | código que não pode virar número |

Sem declaração, o formato é **inferido** pelo nome e pelo tipo da coluna:
`*_porcentagem` → percentual; `valor_*`, `vlr_*`, `preco`, `custo`, `lucro`,
`venda`, `desconto`, `frete` → moeda; inteiro → inteiro; data → data;
`competencia` → mês. Texto fica sem formato.

Duas armadilhas que a inferência já evita:

- **`revenda` não é dinheiro.** Contém "venda", mas é o número da loja — inteiro
  vem antes de moeda na ordem de decisão.
- **Porcentagem não é multiplicada duas vezes.** A gold entrega `12.5` para
  12,5%; o formato `%` nativo do Excel mostraria 1250%. Por isso `percentual`
  usa o `%` como literal.

Quando a inferência errar, declare em `formats` — o declarado sempre vence.

---

## 4. Totais e destaques

**Totais** usam `=SUBTOTAL(109;...)`, não `SOMA`: com o filtro da planilha
ligado, o total passa a ser o do que está sendo mostrado — que é o número que a
pessoa está olhando. A linha de total fica **fora** da faixa do filtro.

**Destaques** são condição SQL avaliada pelo próprio DuckDB sobre o resultado da
aba, então vale qualquer expressão que o SQL entenda:

```yaml
highlights:
  - when: disponivel <= 0 AND reservado > 0
    style: vermelho
  - when: desconto_porcentagem > 10
    style: amarelo
    scope: desconto_porcentagem     # pinta só a célula, não a linha
```

---

## 5. A capa

A primeira aba é sempre a **Capa**: título, descrição, data/hora da geração e
uma linha por aba com o que ela mostra e quantas linhas tem. É o que responde
"de quando é essa planilha?" para quem recebe o arquivo por e-mail ou pela rede.

---

## 6. Relatórios que já existem

| Arquivo | Relatório | Abas |
|---|---|---|
| `10_margem_pecas.yml` | Margem de Peças | Mês atual, Últimos 12 meses, Detalhe |
| `20_ordens_servico.yml` | Ordens de Serviço | Por loja e departamento, Por fonte pagadora, OS do mês |
| `30_estoque_pecas.yml` | Estoque de Peças | Resumo por revenda, Maior valor parado, Zerados com reserva |
| `90_vendas_demo.yml` | Vendas (demonstração) | Mensal por UF, Detalhe |

O `90_vendas_demo.yml` só funciona na base fictícia do `make demo`; num lake
ligado ao ERP ele aparece como `skipped`.

---

## 7. Solução de problemas

| Sintoma | Causa | O que fazer |
|---|---|---|
| Relatório sai como `skipped` | cita um modelo que ainda não existe na gold | rode a carga; confira `datalake query "SELECT * FROM gold.<modelo> LIMIT 1"` |
| `coluna de total inexistente` | nome em `totals` não está no SELECT da aba | use o **alias** da coluna, como ela aparece no cabeçalho |
| Coluna aparece como texto no Excel | valor não numérico vindo da gold | acerte o `CAST` no modelo gold; formato não converte texto em número |
| `R$` numa coluna que é código | o nome bateu com uma pista de dinheiro | declare `formats: {coluna: inteiro}` (ou `texto`) |
| Porcentagem 100× maior | valor entre 0 e 1 com formato `percentual` | use `fracao` |
| Muitas linhas | limite físico do xlsx (1.048.575 por aba) | agregue na aba, use `limit`, ou leve o detalhe pelo `datalake export -f csv` |

---

## 8. Onde está o código

- `src/datalake/report.py` — leitura do YAML, execução das abas, escrita do xlsx.
- `conf/reports/*.yml` — as definições.
- `tests/test_report.py` — testes (inferência de formato, capa, totais, destaque).
