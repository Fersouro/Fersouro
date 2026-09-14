"""Conversao de watermarks entre texto (banco de controle) e valor tipado (bind)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


class WatermarkError(ValueError):
    """Watermark em formato incompativel com o tipo declarado."""


def serialize(value: Any) -> str | None:
    """Converte o valor lido da fonte em texto para gravar no controle."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (Decimal, int, float)):
        return str(value)
    return str(value)


def deserialize(value: str | None, watermark_type: str) -> Any:
    """Converte o texto do controle no tipo usado para filtrar a fonte."""
    if value is None or value == "":
        return None
    kind = watermark_type.lower()
    if kind in ("timestamp", "date"):
        parsed = _parse_datetime(value)
        return parsed.date() if kind == "date" else parsed
    if kind == "number":
        try:
            return Decimal(value)
        except Exception as exc:  # noqa: BLE001
            raise WatermarkError(f"Watermark '{value}' nao e numerico") from exc
    return value


def _parse_datetime(value: str) -> dt.datetime:
    text = value.strip().replace("T", " ", 1)
    for fmt in _TS_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt.replace("T", " ", 1))
        except ValueError:
            continue
    raise WatermarkError(
        f"Watermark '{value}' nao corresponde a um timestamp reconhecido"
    )


def apply_lookback(value: Any, lookback: float, watermark_type: str) -> Any:
    """Recua o watermark para reprocessar uma janela de seguranca.

    Em timestamp/date ``lookback`` esta em dias; em number, e subtraido direto.
    """
    if value is None or not lookback:
        return value
    kind = watermark_type.lower()
    if kind == "timestamp":
        return value - dt.timedelta(days=lookback)
    if kind == "date":
        return value - dt.timedelta(days=int(lookback))
    if kind == "number":
        return value - Decimal(str(lookback))
    return value


def max_from_arrow(table: pa.Table, column: str) -> Any:
    """Maior valor nao nulo de uma coluna (ignora tabelas vazias)."""
    if table.num_rows == 0 or column not in table.column_names:
        return None
    result = pc.max(table.column(column))
    return None if not result.is_valid else result.as_py()


def max_of(current: Any, candidate: Any) -> Any:
    """Maior entre dois watermarks, tolerando None e tipos mistos."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    try:
        return candidate if candidate > current else current
    except TypeError:
        return candidate
