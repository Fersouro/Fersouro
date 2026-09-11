"""Fabrica de conexoes DuckDB usadas nas transformacoes."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from .config import Settings

_SNAKE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_2 = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^0-9a-zA-Z_]+")


def connect(settings: Settings, database: str | Path = ":memory:", read_only: bool = False):
    """Abre uma conexao DuckDB com os limites definidos em settings.yml."""
    if isinstance(database, Path):
        database.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(database), read_only=read_only)
    con.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
    con.execute(f"SET threads = {settings.duckdb_threads}")
    con.execute("SET preserve_insertion_order = false")
    return con


def snake_case(name: str) -> str:
    """CamelCase / NOME DA COLUNA / NR$ITEM -> camel_case, nome_da_coluna, nr_item."""
    text = name.strip()
    if text.isupper():
        text = text.lower()
    else:
        text = _SNAKE_1.sub(r"\1_\2", text)
        text = _SNAKE_2.sub(r"\1_\2", text).lower()
    text = _NON_WORD.sub("_", text).strip("_")
    text = re.sub(r"__+", "_", text)
    if not text:
        return "col"
    if text[0].isdigit():
        text = f"c_{text}"
    return text


def quote(identifier: str) -> str:
    """Aspas duplas para uso seguro em SQL DuckDB."""
    return '"' + identifier.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"
