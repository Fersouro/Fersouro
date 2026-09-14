"""Escrita de lotes Arrow em arquivos Parquet."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from ..logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class WriteResult:
    rows: int = 0
    files: list[Path] = field(default_factory=list)

    @property
    def bytes_written(self) -> int:
        return sum(path.stat().st_size for path in self.files if path.exists())


class ParquetBatchWriter:
    """Escreve lotes Arrow em arquivos Parquet, um arquivo por lote.

    Um arquivo por lote (em vez de um arquivo unico gigante) mantem o uso de
    memoria estavel e permite retomar uma carga interrompida sem reescrever tudo.
    """

    def __init__(
        self,
        directory: Path,
        prefix: str,
        compression: str = "zstd",
        schema: pa.Schema | None = None,
    ) -> None:
        self.directory = directory
        self.prefix = prefix
        self.compression = "none" if compression.lower() == "none" else compression
        self.schema = schema
        self.result = WriteResult()
        self._seq = 0

    def write(self, table: pa.Table) -> Path | None:
        if table.num_rows == 0:
            return None
        if self.schema is not None and not table.schema.equals(self.schema):
            table = table.cast(self.schema)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self.prefix}-{self._seq:03d}.parquet"
        pq.write_table(
            table,
            path,
            compression=self.compression,
            use_dictionary=True,
            version="2.6",
            coerce_timestamps="us",
            allow_truncated_timestamps=True,
        )
        self._seq += 1
        self.result.rows += table.num_rows
        self.result.files.append(path)
        log.debug("Escrito %s (%s linhas)", path.name, f"{table.num_rows:,}")
        return path

    def write_all(self, tables: Iterable[pa.Table]) -> WriteResult:
        for table in tables:
            self.write(table)
        return self.result

    def rollback(self) -> None:
        """Remove os arquivos ja escritos (usado quando a carga falha no meio)."""
        for path in self.result.files:
            path.unlink(missing_ok=True)
        self.result = WriteResult()
        self._seq = 0


def write_single_parquet(table: pa.Table, path: Path, compression: str = "zstd") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        path,
        compression="none" if compression.lower() == "none" else compression,
        use_dictionary=True,
        version="2.6",
    )
    return path


def add_audit_columns(
    table: pa.Table,
    source: str,
    table_name: str,
    batch_id: str,
    ingested_at: pa.TimestampScalar | None = None,
) -> pa.Table:
    """Anexa as colunas de auditoria exigidas na bronze."""
    import datetime as _dt

    rows = table.num_rows
    moment = ingested_at or pa.scalar(
        _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None), type=pa.timestamp("us")
    )
    columns = {
        "_source": pa.array([source] * rows, type=pa.string()),
        "_table": pa.array([table_name] * rows, type=pa.string()),
        "_batch_id": pa.array([batch_id] * rows, type=pa.string()),
        "_ingested_at": pa.array([moment.as_py()] * rows, type=pa.timestamp("us")),
    }
    for name, array in columns.items():
        if name in table.column_names:
            table = table.drop_columns([name])
        table = table.append_column(name, array)
    return table


def iter_row_chunks(table: pa.Table, chunk_rows: int) -> Iterator[pa.Table]:
    """Quebra uma tabela Arrow grande em fatias de ``chunk_rows`` linhas."""
    if chunk_rows <= 0 or table.num_rows <= chunk_rows:
        yield table
        return
    for offset in range(0, table.num_rows, chunk_rows):
        yield table.slice(offset, chunk_rows)
