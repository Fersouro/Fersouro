"""Conector DuckDB: usado no ambiente de demonstracao e nos testes.

Tambem serve para produzir dados a partir de arquivos locais (Parquet/CSV
registrados como views num arquivo .duckdb), sem precisar de um banco externo.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import duckdb
import pyarrow as pa

from ..config import TableConfig
from ..logging_conf import get_logger
from .base import Connector, ConnectorError
from .registry import register_connector

log = get_logger(__name__)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")


def _ident(name: str, what: str) -> str:
    if not _IDENTIFIER.match(name or ""):
        raise ConnectorError(f"{what} invalido: '{name}'")
    return f'"{name}"'


@register_connector
class DuckDBConnector(Connector):
    """Le tabelas de um arquivo DuckDB local."""

    type_name = "duckdb"

    def __init__(self, source: Any, settings: Any) -> None:
        super().__init__(source, settings)
        self._con: duckdb.DuckDBPyConnection | None = None

    def _database_path(self) -> Path:
        database = self.source.connection.get("database")
        if not database:
            raise ConnectorError(
                f"Fonte '{self.source.name}': connection.database e obrigatorio"
            )
        path = Path(database)
        if not path.is_absolute():
            path = (self.settings.project_root / path).resolve()
        return path

    def open(self) -> None:
        if self._con is not None:
            return
        path = self._database_path()
        if not path.exists():
            raise ConnectorError(
                f"Banco DuckDB nao encontrado: {path}. "
                f"Rode 'python scripts/seed_demo.py' para gerar a base de demonstracao."
            )
        self._con = duckdb.connect(str(path), read_only=True)

    def close(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:  # noqa: BLE001
                pass
            self._con = None

    def describe(self) -> str:
        self.open()
        version = self._con.execute("SELECT version()").fetchone()[0]
        return f"DuckDB {version} | arquivo={self._database_path()}"

    # -------------------------------------------------------------------- SQL
    def _relation(self, table: TableConfig) -> str:
        name = _ident(table.name, "Nome de tabela")
        return f"{_ident(table.schema, 'Schema')}.{name}" if table.schema else name

    def _query(self, table: TableConfig, since: Any) -> tuple[str, list[Any]]:
        columns = (
            ", ".join(_ident(c, "Nome de coluna") for c in table.columns)
            if table.columns
            else "*"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None and table.watermark_column:
            clauses.append(f"{_ident(table.watermark_column, 'watermark_column')} > ?")
            params.append(since)
        if table.filter:
            clauses.append(f"({table.filter})")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return f"SELECT {columns} FROM {self._relation(table)}{where}", params

    # --------------------------------------------------------------- extracao
    def count(self, table: TableConfig, since: Any = None) -> int | None:
        self.open()
        sql, params = self._query(table, since)
        return int(
            self._con.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
        )

    def extract(self, table: TableConfig, since: Any = None) -> Iterator[pa.Table]:
        self.open()
        sql, params = self._query(table, since)
        batch_rows = table.batch_rows or self.settings.batch_rows
        log.info("SQL: %s %s", sql, params or "")

        result = self._con.execute(sql, params)
        # to_arrow_reader() e a API atual; fetch_record_batch cobre DuckDB < 1.4.
        reader = (
            result.to_arrow_reader(batch_rows)
            if hasattr(result, "to_arrow_reader")
            else result.fetch_record_batch(batch_rows)
        )
        schema = reader.schema
        yielded = False
        try:
            for batch in reader:
                if batch.num_rows == 0:
                    continue
                yielded = True
                yield pa.Table.from_batches([batch], schema=schema)
        except StopIteration:  # pragma: no cover - fim do stream em versoes antigas
            pass
        if not yielded:
            yield schema.empty_table()
