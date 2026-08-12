#!/usr/bin/env python3
"""Carrega as exportacoes Parquet num banco DuckDB e verifica a integridade.

Fase 4 da migracao, e o passo que transforma arquivos em disco num datalake
que de fato roda. Ate aqui a migracao produzia Parquet solto; isto monta o
banco consultavel.

Roda igual em Windows e Linux — por isso Python, e nao bash ou PowerShell.

Estrutura esperada na entrada (produzida pelos scripts de exportacao):

    DESTINO/
      bigquery/
        lake/<nome_tabela>/*.parquet
        gold/<nome_tabela>/*.parquet
      _migracao-*/manifesto-<dataset>.csv

O manifesto traz o row_count de origem de cada tabela. E contra ele que a
verificacao acontece: sem esse numero, arquivos no disco nao provam nada.

Uso:
  python scripts/carregar_duckdb.py D:/datalake --saida D:/datalake/lake.duckdb
  python scripts/carregar_duckdb.py D:/datalake --views D:/views/gold
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys

# Views do BigQuery referenciam tabelas como `projeto.dataset.tabela`. Aqui
# cada dataset vira um schema do DuckDB, entao a traducao descarta so o
# projeto e preserva dataset.tabela — descartar o dataset tambem faria toda
# view falhar, ja que as tabelas nao vivem no schema padrao.
# Traducao best-effort: o que nao resolver e reportado, nunca silenciado.
REFERENCIA_BQ = re.compile(r"`([A-Za-z0-9_-]+)\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)`")

# Construcoes conhecidas por divergir entre os dois dialetos. Nao tentamos
# reescrever: sinalizamos, porque um ajuste errado aqui muda resultado de
# negocio em silencio — pior que falhar.
#
# Vale para qualquer SQL escrito para o BigQuery, nao so para as views: o
# mapear_dependencias.py usa a mesma lista nas consultas dos sistemas que
# leem o datalake, que precisam da mesma traducao.
CONSTRUCOES_DIVERGENTES = [
    ("QUALIFY", "QUALIFY existe no DuckDB, mas confira a semantica"),
    ("SAFE_CAST", "SAFE_CAST -> TRY_CAST no DuckDB"),
    ("SAFE_DIVIDE", "SAFE_DIVIDE nao existe no DuckDB"),
    ("PARSE_DATE", "PARSE_DATE usa formato diferente (strptime)"),
    ("FORMAT_DATE", "FORMAT_DATE usa formato diferente (strftime)"),
    ("GENERATE_ARRAY", "GENERATE_ARRAY -> generate_series"),
    ("STRUCT<", "tipos STRUCT declarados podem precisar de ajuste"),
    ("_TABLE_SUFFIX", "wildcard de tabela do BigQuery nao existe no DuckDB"),
    ("ARRAY_AGG", "ARRAY_AGG existe, mas confira IGNORE NULLS"),
]


def carregar_manifesto(raiz: str) -> dict[str, dict[str, int]]:
    """Le os manifesto-*.csv e devolve {dataset: {tabela: row_count}}."""
    esperado: dict[str, dict[str, int]] = {}
    for caminho in glob.glob(os.path.join(raiz, "_migracao-*", "manifesto-*.csv")):
        ds = os.path.basename(caminho)[len("manifesto-"):-len(".csv")]
        with open(caminho, newline="", encoding="utf-8-sig") as fh:
            esperado[ds] = {
                linha["table_id"]: int(linha["row_count"] or 0)
                for linha in csv.DictReader(fh)
            }
    return esperado


def traduzir_view(sql: str) -> tuple[str, list[str]]:
    """Adapta DDL de view do BigQuery para DuckDB. Devolve (sql, avisos)."""
    avisos: list[str] = []

    sql = REFERENCIA_BQ.sub(lambda m: f'"{m.group(2)}"."{m.group(3)}"', sql)
    sql = sql.replace("CREATE VIEW", "CREATE OR REPLACE VIEW")

    for termo, nota in CONSTRUCOES_DIVERGENTES:
        if termo in sql.upper():
            avisos.append(nota)

    return sql, avisos


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("raiz", help="pasta de destino da migracao")
    p.add_argument("--saida", default=None, help="arquivo .duckdb (padrao: RAIZ/datalake.duckdb)")
    p.add_argument("--views", default=None, help="pasta com os .sql das views")
    p.add_argument("--datasets", nargs="*", default=["lake", "gold"])
    args = p.parse_args()

    try:
        import duckdb
    except ImportError:
        print("erro: duckdb nao instalado. Rode: pip install duckdb", file=sys.stderr)
        return 2

    raiz = os.path.abspath(args.raiz)
    if not os.path.isdir(raiz):
        print(f"erro: {raiz} nao existe", file=sys.stderr)
        return 2

    saida = args.saida or os.path.join(raiz, "datalake.duckdb")
    esperado = carregar_manifesto(raiz)
    if not esperado:
        print("aviso: nenhum manifesto encontrado — sem contagens de origem,")
        print("       a verificacao fica limitada a 'carregou ou nao'.")

    con = duckdb.connect(saida)
    print(f"banco: {saida}\n")

    divergencias: list[str] = []
    total_linhas = 0
    total_tabelas = 0

    for ds in args.datasets:
        pasta_ds = os.path.join(raiz, "bigquery", ds)
        if not os.path.isdir(pasta_ds):
            print(f"== {ds}: pasta ausente, pulando")
            divergencias.append(f"{ds}: pasta ausente em {pasta_ds}")
            continue

        print(f"== {ds}")
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{ds}"')

        for nome in sorted(os.listdir(pasta_ds)):
            pasta_tab = os.path.join(pasta_ds, nome)
            if not os.path.isdir(pasta_tab):
                continue

            arquivos = glob.glob(os.path.join(pasta_tab, "*.parquet"))
            if not arquivos:
                divergencias.append(f"{ds}.{nome}: pasta sem arquivo .parquet")
                continue

            padrao = os.path.join(pasta_tab, "*.parquet").replace("\\", "/")
            try:
                con.execute(
                    f'CREATE OR REPLACE TABLE "{ds}"."{nome}" AS '
                    f"SELECT * FROM read_parquet('{padrao}')"
                )
                n = con.execute(f'SELECT COUNT(*) FROM "{ds}"."{nome}"').fetchone()[0]
            except Exception as exc:
                divergencias.append(f"{ds}.{nome}: falha ao carregar — {exc}")
                continue

            total_linhas += n
            total_tabelas += 1

            # A verificacao que importa: bate com a origem?
            alvo = esperado.get(ds, {}).get(nome)
            if alvo is None:
                print(f"   {nome}: {n:,} linhas (sem referencia no manifesto)")
            elif alvo != n:
                print(f"   {nome}: {n:,} linhas  DIVERGE (origem: {alvo:,})")
                divergencias.append(f"{ds}.{nome}: origem {alvo}, carregado {n}")
            else:
                print(f"   {nome}: {n:,} linhas  ok")

        # Tabelas que existiam na origem e nao chegaram.
        chegaram = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                [ds],
            ).fetchall()
        }
        for faltante in sorted(set(esperado.get(ds, {})) - chegaram):
            divergencias.append(f"{ds}.{faltante}: presente na origem, ausente no destino")

    # --- Views ---------------------------------------------------------------
    avisos_views: list[str] = []
    if args.views:
        print("\n== views")
        arquivos = sorted(glob.glob(os.path.join(args.views, "*.sql")))
        if not arquivos:
            print(f"   nenhum .sql em {args.views}")
        for caminho in arquivos:
            nome = os.path.splitext(os.path.basename(caminho))[0]
            sql, avisos = traduzir_view(open(caminho, encoding="utf-8").read())
            try:
                con.execute(sql)
                marca = "ok" if not avisos else "ok (com ressalvas)"
                print(f"   {nome}: {marca}")
            except Exception as exc:
                print(f"   {nome}: FALHOU — {exc}")
                divergencias.append(f"view {nome}: {exc}")
                avisos.append("precisa de traducao manual")
            for a in avisos:
                avisos_views.append(f"{nome}: {a}")

    con.close()

    # --- Veredito ------------------------------------------------------------
    print(f"\ncarregadas {total_tabelas} tabelas, {total_linhas:,} linhas")

    if avisos_views:
        print("\nRessalvas nas views (revise manualmente):")
        for a in avisos_views:
            print(f"  - {a}")

    if divergencias:
        print(f"\nVERIFICACAO FALHOU ({len(divergencias)}):")
        for d in divergencias[:40]:
            print(f"  - {d}")
        if len(divergencias) > 40:
            print(f"  ... e mais {len(divergencias) - 40}")
        print("\nNAO prossiga para a desativacao da conta GCP.")
        return 1

    print("\nVERIFICADO: tudo confere com o manifesto de origem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
