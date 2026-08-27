# Estoque Mínimo de Peças — Revenda 1

Consulta analítica que aponta **quais peças da Revenda 1 estão em ruptura ou abaixo
do estoque mínimo** e **quanto comprar** de cada uma.

| Arquivo | Uso |
|---|---|
| `estoque_minimo_revenda1.sql` | Spark SQL / Databricks — consulta ad-hoc no editor do Data Lake |
| `estoque_minimo_revenda1_pyspark.py` | Mesma lógica em PySpark, para job/pipeline |

## Raciocínio da query (passo a passo)

1. **`parametros`** — a revenda alvo fica isolada em um único ponto (`p_id_revenda = 1`).
   Trocar de revenda, ou parametrizar via widget/variável, é mexer em uma linha só.
2. **`ultima_carga`** — fato de estoque quase sempre é *snapshot* diário particionado
   por data. Sem recortar a data máxima, a mesma peça retornaria uma vez por dia de
   carga e os números sairiam multiplicados. Este é o erro mais comum nesse tipo de análise.
3. **`estoque_bruto`** — aplica o filtro rigoroso da revenda **antes** de qualquer join.
   Como `id_revenda` e `dt_referencia` costumam ser colunas de partição, o *predicate
   pushdown* faz o engine ler só os arquivos necessários. `COALESCE(...,0)` evita que
   `NULL` contamine as comparações (em SQL, `NULL <= 5` não é verdadeiro nem falso).
4. **`estoque_consolidado`** — se o grão do fato for menor que a peça (depósito, lote,
   prateleira), consolida em uma linha por peça: `SUM` no estoque atual e `MAX` no
   mínimo (mínimo é *parâmetro do item*, não quantidade — somar duplicaria a meta).
5. **`classificado`** — regras de negócio:
   - `quantidade_reposicao = GREATEST(estoque_minimo - estoque_atual, 0)` → nunca negativa;
   - `CASE` de status na ordem correta (`<= 0` testado primeiro, senão a ruptura seria
     classificada como "Abaixo do Mínimo");
   - `LEFT JOIN` com a dimensão para **não perder** peça sem cadastro — ela aparece como
     `(SEM CADASTRO NA DIMENSÃO)`, que já é um achado de qualidade de dados.
6. **`ORDER BY`** — `ordem_prioridade` (1 Crítico → 2 Abaixo → 3 Ok), depois
   `quantidade_reposicao DESC` (maior déficit primeiro) e a descrição como desempate
   estável, para o resultado não variar entre execuções.

## Decisões que você pode querer inverter

| Decisão tomada | Onde mudar | Por quê |
|---|---|---|
| `WHERE estoque_minimo > 0` | último `WHERE` | peça sem política de mínimo cadastrada e estoque 0 apareceria como "Crítico" e inundaria o relatório com falso positivo. Remova se quiser ver tudo. |
| `status_estoque <> 'Ok'` | último `WHERE` | o enunciado pede o filtro `atual <= mínimo`, mas a coluna de status prevê `Ok`. Deixei a classificação completa e o corte comentável: **comente a linha** para trazer os itens `Ok` também (útil para Power BI, onde o filtro fica no visual). |
| `estoque_atual <= 0` para "Crítico" | `CASE` | usei `<= 0` em vez de `= 0` porque estoque negativo (erro de baixa/inventário) é ruptura na prática, e com `= 0` ele escaparia da categoria mais grave. |
| Snapshot da última data | `ultima_carga` | se o fato já for "estado atual" (uma linha por peça, sem histórico), remova a CTE e o join com ela. |

## Adaptação de nomes

Todos os pontos a trocar estão marcados com `-- <<< ADAPTAR` no `.sql` e no bloco
`CONFIG` do `.py`. Mapeamento presumido:

| Papel | Nome usado aqui | Alternativas comuns |
|---|---|---|
| Fato | `datalake.gold.fato_estoque` | `fato_saldo_estoque`, `f_estoque`, `tb_estoque` |
| Dimensão | `datalake.gold.dim_produto` | `dim_peca`, `d_produto`, `cad_produto` |
| Revenda | `id_revenda` | `cod_revenda`, `id_filial`, `cod_empresa`, `id_loja` |
| Peça | `id_produto` | `sk_produto`, `cod_peca`, `id_item` |
| Data do snapshot | `dt_referencia` | `data_particao`, `dt_foto`, `dt_carga`, `anomesdia` |
| Estoque atual | `qtd_estoque_atual` | `saldo_atual`, `qtd_saldo`, `estoque_disponivel` |
| Estoque mínimo | `qtd_estoque_minimo` | `estoque_min`, `ponto_pedido`, `qtd_min` |

## Outros dialetos

- **Trino / Athena / Presto** — roda como está; se a dimensão for pequena, troque o
  `LEFT JOIN` por `LEFT JOIN ... /*+ ... */` ou confie no *broadcast* automático.
- **SQL Server** — não tem `GREATEST` antes do SQL Server 2022. Substitua por:
  `CASE WHEN e.estoque_minimo - e.estoque_atual > 0 THEN e.estoque_minimo - e.estoque_atual ELSE 0 END`.
  `CAST(... AS DECIMAL(18,3))` e as CTEs funcionam sem alteração.
- **Firebird** — sem `GREATEST` (use o `CASE` acima) e sem `CROSS JOIN parametros`:
  troque por literal `1` ou por parâmetro `:ID_REVENDA`. CTEs (`WITH`) exigem Firebird 2.1+.
- **Power BI / DirectQuery** — remova o `ORDER BY` (o visual ordena) e mantenha os itens
  `Ok` no resultado, para que os cartões de "% de itens em ruptura" tenham denominador.
