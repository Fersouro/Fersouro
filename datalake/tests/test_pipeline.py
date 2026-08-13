"""Pipeline ponta a ponta: bronze -> silver -> gold -> qualidade -> catalogo."""

from __future__ import annotations

import datetime as dt

import duckdb
import pytest

from datalake.catalog.builder import build_catalog
from datalake.duck import snake_case
from datalake.layers import bronze, gold, silver
from datalake.quality.checks import run_table_checks
from datalake.state.control import new_run_id
from datalake.storage import paths

from conftest import BASE


def _ingest(settings, control, **kwargs):
    return bronze.ingest_source(
        settings, settings.source("erp"), control, new_run_id(), **kwargs
    )


def _silver(settings, control):
    return silver.build_source(settings, settings.source("erp"), control, new_run_id())


def _rows(path, sql="SELECT count(*) FROM read_parquet(?)"):
    con = duckdb.connect()
    try:
        return con.execute(sql, [paths.glob_parquet(path)]).fetchone()[0]
    finally:
        con.close()


# ----------------------------------------------------------------- bronze
def test_bronze_grava_todas_as_tabelas(settings, control):
    resultados = _ingest(settings, control)
    assert [r.status for r in resultados] == ["success", "success"]
    assert {r.table: r.rows for r in resultados} == {"clientes": 3, "pedidos": 3}

    destino = paths.bronze_table_dir(settings.root, "erp", "pedidos")
    arquivos = list(destino.rglob("*.parquet"))
    assert len(arquivos) == 1
    assert arquivos[0].parent.name.startswith("_ingest_date=")


def test_bronze_acrescenta_colunas_de_auditoria(settings, control):
    _ingest(settings, control)
    destino = paths.bronze_table_dir(settings.root, "erp", "clientes")
    con = duckdb.connect()
    colunas = {
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{paths.glob_parquet(destino)}')"
        ).fetchall()
    }
    con.close()
    assert {"_source", "_table", "_batch_id", "_ingested_at"} <= colunas


def test_watermark_e_registrado_e_reutilizado(settings, control, project):
    _ingest(settings, control)
    estado = control.get_state("erp", "pedidos")
    assert estado.watermark_value.startswith("2026-01-10 08:10")

    # Nada novo na origem: a segunda carga nao traz linhas.
    resultados = _ingest(settings, control)
    assert next(r for r in resultados if r.table == "pedidos").rows == 0


def test_carga_incremental_traz_apenas_o_que_mudou(settings, control, project):
    _ingest(settings, control)
    con = duckdb.connect(str(project / "origem.duckdb"))
    con.execute(
        "INSERT INTO pedidos VALUES (13, 1, 'A', 500.00, ?)",
        [BASE + dt.timedelta(hours=2)],
    )
    con.execute(
        "UPDATE pedidos SET vlr_total = 999.99, dt_atualizacao = ? WHERE id_pedido = 10",
        [BASE + dt.timedelta(hours=3)],
    )
    con.close()

    resultados = _ingest(settings, control)
    assert next(r for r in resultados if r.table == "pedidos").rows == 2


def test_carga_full_substitui_a_particao_do_dia(settings, control):
    _ingest(settings, control)
    _ingest(settings, control)
    destino = paths.bronze_table_dir(settings.root, "erp", "clientes")
    # 'clientes' e full: rerodar no mesmo dia troca os arquivos, nao acumula.
    assert _rows(destino) == 3


def test_flag_full_ignora_o_watermark(settings, control):
    _ingest(settings, control)
    resultados = _ingest(settings, control, full=True)
    assert next(r for r in resultados if r.table == "pedidos").rows == 3


def test_dry_run_nao_escreve(settings, control):
    resultados = _ingest(settings, control, dry_run=True)
    assert all(r.status == "skipped" for r in resultados)
    assert not any(settings.bronze.rglob("*.parquet"))


def test_falha_de_uma_tabela_nao_derruba_as_outras(settings, control, project):
    duckdb.connect(str(project / "origem.duckdb")).execute("DROP TABLE pedidos")
    resultados = _ingest(settings, control)
    por_tabela = {r.table: r.status for r in resultados}
    assert por_tabela == {"clientes": "success", "pedidos": "failed"}
    assert not list(settings.bronze.glob("erp/pedidos/*/*.parquet"))


# ----------------------------------------------------------------- silver
def test_silver_normaliza_e_deduplica(settings, control, project):
    _ingest(settings, control)
    con = duckdb.connect(str(project / "origem.duckdb"))
    con.execute(
        "UPDATE pedidos SET vlr_total = 777.77, dt_atualizacao = ? WHERE id_pedido = 10",
        [BASE + dt.timedelta(hours=1)],
    )
    con.close()
    _ingest(settings, control)

    assert [r.status for r in _silver(settings, control)] == ["success", "success"]

    destino = paths.silver_table_dir(settings.root, "erp", "pedidos")
    assert _rows(destino) == 3  # continua uma linha por pedido

    valor = duckdb.connect().execute(
        f"SELECT vlr_total FROM read_parquet('{paths.glob_parquet(destino)}') "
        f"WHERE id_pedido = 10"
    ).fetchone()[0]
    assert float(valor) == pytest.approx(777.77)  # ficou a versao mais recente


def test_silver_ignorada_quando_a_bronze_esta_vazia(settings, control):
    resultados = _silver(settings, control)
    assert all(r.status == "skipped" for r in resultados)


def test_silver_aceita_sql_customizado(settings, control, project):
    _ingest(settings, control)
    custom = project / "sql" / "silver"
    custom.mkdir(parents=True)
    (custom / "erp__clientes.sql").write_text(
        "SELECT id_cliente, upper(nome) AS nome FROM {{bronze}} WHERE uf = 'MG'",
        encoding="utf-8",
    )
    _silver(settings, control)
    destino = paths.silver_table_dir(settings.root, "erp", "clientes")
    con = duckdb.connect()
    linhas = con.execute(
        f"SELECT id_cliente, nome FROM read_parquet('{paths.glob_parquet(destino)}')"
    ).fetchall()
    con.close()
    assert linhas == [(1, "ALFA")]


# ------------------------------------------------------------------- gold
def test_gold_materializa_o_modelo(settings, control):
    _ingest(settings, control)
    _silver(settings, control)
    resultados = gold.build_all(settings, control, new_run_id())
    assert [(r.model, r.status, r.rows) for r in resultados] == [
        ("pedidos_cliente", "success", 2)  # o pedido cancelado fica de fora
    ]
    assert (settings.gold / "pedidos_cliente" / "data.parquet").exists()


def test_gold_modelo_inexistente(settings, control):
    with pytest.raises(ValueError, match="inexistente"):
        gold.build_all(settings, control, new_run_id(), only=["nao_existe"])


# -------------------------------------------------------------- qualidade
def test_qualidade_aprova_dados_integros(settings, control):
    _ingest(settings, control)
    _silver(settings, control)
    source = settings.source("erp")
    resultados = [
        r for t in source.tables for r in run_table_checks(settings, source, t)
    ]
    assert resultados and all(r.status == "pass" for r in resultados)


def test_qualidade_reprova_nulo_e_duplicidade(settings, control, project):
    con = duckdb.connect(str(project / "origem.duckdb"))
    con.execute("INSERT INTO clientes VALUES (1, NULL, 'MG')")  # duplica pk e nome nulo
    con.close()
    _ingest(settings, control)

    # A silver deduplica pela pk, entao a duplicidade some e o nulo permanece.
    _silver(settings, control)
    source = settings.source("erp")
    resultados = run_table_checks(settings, source, source.table("clientes"))
    reprovados = {r.check_name for r in resultados if r.status == "fail"}
    assert reprovados == {"not_null"}
    assert all(r.blocking for r in resultados if r.status == "fail")


def test_qualidade_sinaliza_coluna_inexistente(settings, control):
    _ingest(settings, control)
    _silver(settings, control)
    source = settings.source("erp")
    table = source.table("clientes")
    quebrada = type(table)(**{**table.__dict__, "quality": {"not_null": ["cnpj"]}})
    resultados = run_table_checks(settings, source, quebrada)
    assert [r.status for r in resultados] == ["error"]


# --------------------------------------------------------------- catalogo
def test_catalogo_registra_silver_e_gold(settings, control):
    _ingest(settings, control)
    _silver(settings, control)
    gold.build_all(settings, control, new_run_id())

    entradas = build_catalog(settings)
    nomes = {(e.schema, e.name) for e in entradas}
    assert ("silver", "erp__clientes") in nomes
    assert ("gold", "pedidos_cliente") in nomes

    con = duckdb.connect(str(settings.catalog_db), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM silver.erp__pedidos").fetchone()[0] == 3
        assert con.execute("SELECT count(*) FROM lake_objects").fetchone()[0] == len(nomes)
    finally:
        con.close()


# ------------------------------------------------------------------- util
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("ID_CLIENTE", "id_cliente"),
        ("IdCliente", "id_cliente"),
        ("NR$ITEM", "nr_item"),
        ("Valor Total", "valor_total"),
        ("2VIA", "c_2via"),
        ("  ", "col"),
    ],
)
def test_snake_case(entrada, esperado):
    assert snake_case(entrada) == esperado
