"""Serializacao, lookback e comparacao de watermarks."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pyarrow as pa
import pytest

from datalake.state import watermark as wm


def test_timestamp_ida_e_volta():
    valor = dt.datetime(2026, 3, 1, 14, 30, 15, 123456)
    texto = wm.serialize(valor)
    assert texto == "2026-03-01 14:30:15.123456"
    assert wm.deserialize(texto, "timestamp") == valor


def test_date_ida_e_volta():
    assert wm.deserialize(wm.serialize(dt.date(2026, 3, 1)), "date") == dt.date(2026, 3, 1)


def test_numero_vira_decimal():
    assert wm.deserialize(wm.serialize(Decimal("1234.56")), "number") == Decimal("1234.56")


def test_timestamp_sem_microssegundos_e_iso():
    assert wm.deserialize("2026-03-01T14:30:15", "timestamp") == dt.datetime(
        2026, 3, 1, 14, 30, 15
    )


def test_nulos():
    assert wm.serialize(None) is None
    assert wm.deserialize(None, "timestamp") is None
    assert wm.deserialize("", "number") is None


def test_formato_invalido():
    with pytest.raises(wm.WatermarkError):
        wm.deserialize("ontem", "timestamp")
    with pytest.raises(wm.WatermarkError):
        wm.deserialize("abc", "number")


def test_lookback_recua_a_janela():
    valor = dt.datetime(2026, 3, 10, 12, 0, 0)
    assert wm.apply_lookback(valor, 1, "timestamp") == dt.datetime(2026, 3, 9, 12, 0, 0)
    assert wm.apply_lookback(valor, 0, "timestamp") == valor
    assert wm.apply_lookback(None, 5, "timestamp") is None
    assert wm.apply_lookback(Decimal("100"), 10, "number") == Decimal("90")


def test_maior_valor_do_arrow():
    tabela = pa.table(
        {"dt": pa.array([dt.datetime(2026, 1, 1), None, dt.datetime(2026, 5, 5)])}
    )
    assert wm.max_from_arrow(tabela, "dt") == dt.datetime(2026, 5, 5)
    assert wm.max_from_arrow(tabela, "inexistente") is None
    assert wm.max_from_arrow(tabela.slice(0, 0), "dt") is None


def test_tabela_so_com_nulos_nao_gera_watermark():
    tabela = pa.table({"dt": pa.array([None, None], type=pa.timestamp("us"))})
    assert wm.max_from_arrow(tabela, "dt") is None


def test_max_of_tolera_none():
    assert wm.max_of(None, 5) == 5
    assert wm.max_of(5, None) == 5
    assert wm.max_of(5, 9) == 9
    assert wm.max_of(9, 5) == 9
