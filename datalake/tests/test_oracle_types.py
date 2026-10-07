"""Mapeamento de tipos Oracle -> Arrow e montagem do SQL de extracao."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pyarrow as pa
import pytest

from datalake.config import Settings, SourceConfig, TableConfig
from datalake.connectors.base import ConnectorError
from datalake.connectors.oracle import (
    OracleConnector,
    _check_identifier,
    _coerce,
    _number_to_arrow,
    _parse_type_override,
    _rows_to_arrow,
)


# ------------------------------------------------------------------ NUMBER
def test_number_inteiro_pequeno_vira_int64():
    assert _number_to_arrow(10, 0) == pa.int64()


def test_number_inteiro_grande_vira_decimal():
    assert _number_to_arrow(25, 0) == pa.decimal128(25, 0)


def test_number_com_escala_vira_decimal():
    assert _number_to_arrow(18, 4) == pa.decimal128(18, 4)


def test_number_sem_precisao_vira_float():
    # Oracle reporta precision=0 e scale=-127 para NUMBER sem restricao.
    assert _number_to_arrow(0, -127) == pa.float64()
    assert _number_to_arrow(None, None) == pa.float64()


def test_number_com_escala_negativa():
    assert _number_to_arrow(5, -2) == pa.decimal128(7, 0)


def test_precisao_maior_que_38_e_limitada():
    assert _number_to_arrow(60, 2) == pa.decimal128(38, 2)


# ------------------------------------------------------------- column_types
def test_override_de_tipo():
    assert _parse_type_override("decimal(18,4)") == pa.decimal128(18, 4)
    assert _parse_type_override("STRING") == pa.string()
    assert _parse_type_override(" int64 ") == pa.int64()


def test_override_desconhecido():
    with pytest.raises(ConnectorError, match="nao reconhecido"):
        _parse_type_override("numerico")


# ------------------------------------------------------------------ coercao
def test_coercao_para_int_aceita_decimal_e_nulo():
    array = _coerce([Decimal("7"), None, 9], pa.int64(), "id")
    assert array.to_pylist() == [7, None, 9]


def test_coercao_para_decimal_ajusta_escala():
    array = _coerce([Decimal("10.123456"), None], pa.decimal128(18, 2), "vlr")
    assert array.to_pylist() == [Decimal("10.12"), None]


def test_coercao_para_texto_decodifica_bytes():
    array = _coerce([b"ok", "ja e texto", None], pa.string(), "obs")
    assert array.to_pylist() == ["ok", "ja e texto", None]


def test_coercao_de_data_para_timestamp():
    array = _coerce([dt.date(2026, 2, 1), None], pa.timestamp("us"), "dt")
    assert array.to_pylist() == [dt.datetime(2026, 2, 1), None]


def test_coercao_invalida_aponta_a_coluna():
    with pytest.raises(ConnectorError, match="vlr"):
        _coerce(["abc"], pa.int64(), "vlr")


def test_linhas_viram_tabela_arrow_com_o_schema_declarado():
    schema = pa.schema([("id", pa.int64()), ("nome", pa.string())])
    tabela = _rows_to_arrow([(1, "a"), (2, None)], schema)
    assert tabela.schema == schema
    assert tabela.to_pydict() == {"id": [1, 2], "nome": ["a", None]}


# ------------------------------------------------------------- identificador
def test_identificador_valido():
    assert _check_identifier("ID_PEDIDO$1", "coluna") == "ID_PEDIDO$1"


@pytest.mark.parametrize("nome", ["", "1_COL", "COL; DROP TABLE X", "A B", "'x'"])
def test_identificador_invalido(nome):
    with pytest.raises(ConnectorError):
        _check_identifier(nome, "coluna")


# ---------------------------------------------------------------------- SQL
def _connector(settings: Settings) -> OracleConnector:
    source = SourceConfig.from_dict(
        {
            "name": "erp",
            "type": "oracle",
            "connection": {"dsn": "h:1521/x", "user": "u", "password": "p"},
            "tables": ["DUAL"],
        }
    )
    return OracleConnector(source, settings)


def test_sql_de_carga_total(settings):
    table = TableConfig(name="CLIENTES", schema="ERP")
    sql, binds = _connector(settings)._build_query(table, None)
    assert sql == "SELECT * FROM ERP.CLIENTES"
    assert binds == {}


def test_sql_incremental_usa_bind(settings):
    table = TableConfig(
        name="PEDIDOS",
        schema="ERP",
        load_mode="incremental",
        watermark_column="DT_ATUALIZACAO",
        primary_key=("ID",),
    )
    momento = dt.datetime(2026, 1, 1)
    sql, binds = _connector(settings)._build_query(table, momento)
    assert sql == "SELECT * FROM ERP.PEDIDOS WHERE DT_ATUALIZACAO > :wm"
    assert binds == {"wm": momento}


def test_sql_com_projecao_e_filtro(settings):
    table = TableConfig(
        name="ITENS",
        schema="ERP",
        columns=("ID", "VLR"),
        filter="SITUACAO <> 'X'",
    )
    sql, _ = _connector(settings)._build_query(table, None)
    assert sql == "SELECT ID, VLR FROM ERP.ITENS WHERE (SITUACAO <> 'X')"


def test_sql_rejeita_nome_de_tabela_suspeito(settings):
    table = TableConfig(name="CLIENTES; DELETE FROM X")
    with pytest.raises(ConnectorError):
        _connector(settings)._build_query(table, None)


# ------------------------------------------------- barreira de somente leitura
@pytest.mark.parametrize(
    "consulta",
    [
        "UPDATE VEI_VEICULO SET PRECO = 0",
        "delete from vei_veiculo",
        "DROP TABLE VEI_VEICULO",
        "TRUNCATE TABLE X",
        "BEGIN meu_proc; END;",
        "MERGE INTO X USING Y ON (1=1)",
    ],
)
def test_run_select_recusa_escrita(settings, consulta):
    """A conexao pode ser a do dono do schema: escrita nao passa por aqui."""
    conector = _connector(settings)
    conector._con = object()          # nao deve chegar a usar a conexao
    conector.open = lambda: None
    with pytest.raises(ConnectorError, match="Apenas leitura|uma consulta por vez"):
        conector.run_select(consulta)


def test_run_select_recusa_multiplos_comandos(settings):
    conector = _connector(settings)
    conector.open = lambda: None
    with pytest.raises(ConnectorError, match="uma consulta por vez"):
        conector.run_select("SELECT 1 FROM dual; DROP TABLE X")


def test_run_select_recusa_consulta_vazia(settings):
    conector = _connector(settings)
    conector.open = lambda: None
    with pytest.raises(ConnectorError, match="vazia"):
        conector.run_select("   ")
