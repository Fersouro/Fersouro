"""
Análise de Estoque Mínimo de Peças | Revenda 1 — versão PySpark (DataFrame API).

Equivalente 1:1 ao arquivo estoque_minimo_revenda1.sql.
Use esta versão quando a análise fizer parte de um job/pipeline (Databricks,
EMR, Glue); use o .sql quando for consulta ad-hoc no editor do Data Lake.

>>> PONTOS DE ADAPTAÇÃO: bloco CONFIG abaixo. <<<
"""

from pyspark.sql import SparkSession, functions as F

# ----------------------------------------------------------------------------
# CONFIG — ajuste apenas aqui os nomes reais de tabelas/colunas
# ----------------------------------------------------------------------------
CONFIG = {
    "tabela_fato":        "datalake.gold.fato_estoque",
    "tabela_dim":         "datalake.gold.dim_produto",
    # colunas do fato
    "col_id_produto_fato": "id_produto",
    "col_id_revenda":      "id_revenda",
    "col_dt_referencia":   "dt_referencia",     # coluna de partição / data do snapshot
    "col_estoque_atual":   "qtd_estoque_atual",
    "col_estoque_minimo":  "qtd_estoque_minimo",
    # colunas da dimensão
    "col_id_produto_dim":  "id_produto",
    "col_codigo_peca":     "cod_peca",
    "col_descricao":       "descricao_produto",
    # parâmetros de negócio
    "id_revenda":          1,
    "fator_reposicao":     1.0,    # lote de compra = estoque_minimo * fator
    "somente_pendentes":   True,   # False => traz também os itens com status 'Ok'
}


def analisar_estoque_minimo(spark: SparkSession, cfg: dict = CONFIG):
    c = cfg

    # 1) Filtro principal: SOMENTE a revenda alvo (empurrado para o predicado
    #    de partição, então o Spark lê só os arquivos dessa revenda).
    fato = (
        spark.table(c["tabela_fato"])
             .where(F.col(c["col_id_revenda"]) == F.lit(c["id_revenda"]))
    )

    # 2) Snapshot mais recente (fatos de estoque costumam ser foto diária).
    dt_max = fato.agg(F.max(c["col_dt_referencia"]).alias("dt")).collect()[0]["dt"]
    fato = fato.where(F.col(c["col_dt_referencia"]) == F.lit(dt_max))

    # 3) Consolidação por peça (caso o grão seja depósito/lote/prateleira).
    estoque = (
        fato.select(
                F.col(c["col_id_produto_fato"]).alias("id_peca"),
                F.col(c["col_id_revenda"]).alias("revenda"),
                F.coalesce(F.col(c["col_estoque_atual"]),  F.lit(0))
                 .cast("decimal(18,3)").alias("estoque_atual"),
                F.coalesce(F.col(c["col_estoque_minimo"]), F.lit(0))
                 .cast("decimal(18,3)").alias("estoque_minimo"),
            )
            .groupBy("id_peca", "revenda")
            .agg(
                F.sum("estoque_atual").alias("estoque_atual"),
                F.max("estoque_minimo").alias("estoque_minimo"),  # mínimo é parâmetro, não soma
            )
    )

    # 4) Enriquecimento com a dimensão (LEFT: não perder peça sem cadastro).
    dim = spark.table(c["tabela_dim"]).select(
        F.col(c["col_id_produto_dim"]).alias("_id_dim"),
        F.col(c["col_codigo_peca"]).alias("codigo_peca"),
        F.col(c["col_descricao"]).alias("descricao_peca"),
    )
    df = estoque.join(dim, estoque["id_peca"] == dim["_id_dim"], "left").drop("_id_dim")

    # 5) Regras de negócio: déficit + classificação de risco.
    df = (
        df.withColumn(
              "quantidade_reposicao",
              F.greatest(F.col("estoque_minimo") - F.col("estoque_atual"), F.lit(0)),
          )
          # Peça exatamente no mínimo tem déficit 0, e pedido de 0 peça não serve:
          # o lote de compra é estoque_minimo * fator, e leva-se o maior dos dois.
          .withColumn(
              "quantidade_comprar",
              F.greatest(
                  F.col("quantidade_reposicao"),
                  F.round(F.col("estoque_minimo") * F.lit(c["fator_reposicao"]), 0),
              ),
          )
          .withColumn(
              "status_estoque",
              F.when(F.col("estoque_atual") <= 0, F.lit("Crítico"))
               .when(F.col("estoque_atual") < F.col("estoque_minimo"), F.lit("Abaixo do Mínimo"))
               .when(F.col("estoque_atual") == F.col("estoque_minimo"), F.lit("No Mínimo"))
               .otherwise(F.lit("Ok")),
          )
          .withColumn(
              "ordem_prioridade",
              F.when(F.col("estoque_atual") <= 0, F.lit(1))
               .when(F.col("estoque_atual") < F.col("estoque_minimo"), F.lit(2))
               .when(F.col("estoque_atual") == F.col("estoque_minimo"), F.lit(3))
               .otherwise(F.lit(4)),
          )
          .withColumn(
              "descricao_peca",
              F.coalesce(F.col("descricao_peca"), F.lit("(SEM CADASTRO NA DIMENSÃO)")),
          )
          .where(F.col("estoque_minimo") > 0)  # ignora peças sem política de mínimo
    )

    if c["somente_pendentes"]:
        df = df.where(F.col("status_estoque") != F.lit("Ok"))

    # 6) Ordenação: ruptura primeiro, depois maior déficit.
    return (
        df.select(
              "id_peca", "codigo_peca", "descricao_peca", "revenda",
              "estoque_atual", "estoque_minimo", "quantidade_reposicao",
              "quantidade_comprar", "status_estoque", "ordem_prioridade",
          )
          .orderBy(
              F.col("ordem_prioridade").asc(),
              F.col("quantidade_comprar").desc(),
              F.col("estoque_minimo").desc(),
              F.col("codigo_peca").asc(),
          )
          .drop("ordem_prioridade")
    )


if __name__ == "__main__":
    spark = SparkSession.builder.appName("estoque_minimo_revenda_1").getOrCreate()
    analisar_estoque_minimo(spark).show(100, truncate=False)
