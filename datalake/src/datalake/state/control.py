"""Banco de controle (DuckDB): watermarks, log de execucao e qualidade.

Cada operacao abre e fecha a conexao. DuckDB permite apenas um processo escritor
por arquivo, entao segurar a conexao aberta impediria rodar duas cargas em
paralelo em processos diferentes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import duckdb

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS ingestion_state (
        source           VARCHAR NOT NULL,
        table_name       VARCHAR NOT NULL,
        watermark_value  VARCHAR,
        watermark_type   VARCHAR,
        last_run_id      VARCHAR,
        last_status      VARCHAR,
        last_run_at      TIMESTAMP,
        rows_last_run    BIGINT DEFAULT 0,
        rows_total       BIGINT DEFAULT 0,
        PRIMARY KEY (source, table_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_log (
        run_id          VARCHAR NOT NULL,
        layer           VARCHAR NOT NULL,
        source          VARCHAR,
        table_name      VARCHAR,
        status          VARCHAR NOT NULL,
        rows            BIGINT DEFAULT 0,
        started_at      TIMESTAMP NOT NULL,
        finished_at     TIMESTAMP,
        duration_s      DOUBLE,
        watermark_from  VARCHAR,
        watermark_to    VARCHAR,
        message         VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quality_results (
        run_id       VARCHAR,
        checked_at   TIMESTAMP NOT NULL,
        source       VARCHAR,
        table_name   VARCHAR,
        check_name   VARCHAR,
        column_name  VARCHAR,
        status       VARCHAR,
        observed     VARCHAR,
        details      VARCHAR
    )
    """,
)


def utcnow() -> dt.datetime:
    """Agora em UTC, sem tzinfo (DuckDB TIMESTAMP nao guarda fuso)."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def new_run_id() -> str:
    return f"{utcnow():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


@dataclass
class TableState:
    source: str
    table_name: str
    watermark_value: str | None
    watermark_type: str | None
    last_run_id: str | None
    last_status: str | None
    last_run_at: dt.datetime | None
    rows_last_run: int
    rows_total: int


class ControlDB:
    """Acesso ao banco de controle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        con = duckdb.connect(str(self.path))
        try:
            yield con
        finally:
            con.close()

    def init_schema(self) -> None:
        with self.connect() as con:
            for statement in SCHEMA_STATEMENTS:
                con.execute(statement)

    # ------------------------------------------------------------------ state
    def get_state(self, source: str, table_name: str) -> TableState | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT source, table_name, watermark_value, watermark_type, last_run_id,
                       last_status, last_run_at, rows_last_run, rows_total
                  FROM ingestion_state
                 WHERE source = ? AND table_name = ?
                """,
                [source, table_name],
            ).fetchone()
        return TableState(*row) if row else None

    def get_watermark(self, source: str, table_name: str) -> str | None:
        state = self.get_state(source, table_name)
        return state.watermark_value if state else None

    def save_state(
        self,
        source: str,
        table_name: str,
        *,
        watermark_value: str | None,
        watermark_type: str | None,
        run_id: str,
        status: str,
        rows: int,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO ingestion_state AS s
                    (source, table_name, watermark_value, watermark_type, last_run_id,
                     last_status, last_run_at, rows_last_run, rows_total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source, table_name) DO UPDATE SET
                    watermark_value = COALESCE(excluded.watermark_value, s.watermark_value),
                    watermark_type  = excluded.watermark_type,
                    last_run_id     = excluded.last_run_id,
                    last_status     = excluded.last_status,
                    last_run_at     = excluded.last_run_at,
                    rows_last_run   = excluded.rows_last_run,
                    rows_total      = s.rows_total + excluded.rows_last_run
                """,
                [
                    source,
                    table_name,
                    watermark_value,
                    watermark_type,
                    run_id,
                    status,
                    utcnow(),
                    rows,
                    rows,
                ],
            )

    def reset_state(self, source: str, table_name: str | None = None) -> int:
        """Zera o watermark para forcar recarga total na proxima execucao."""
        with self.connect() as con:
            if table_name:
                cur = con.execute(
                    "DELETE FROM ingestion_state WHERE source = ? AND table_name = ?",
                    [source, table_name],
                )
            else:
                cur = con.execute(
                    "DELETE FROM ingestion_state WHERE source = ?", [source]
                )
            return cur.fetchall()[0][0] if cur.description else 0

    def list_state(self) -> list[tuple[Any, ...]]:
        with self.connect() as con:
            return con.execute(
                """
                SELECT source, table_name, last_status, watermark_value,
                       last_run_at, rows_last_run, rows_total
                  FROM ingestion_state
                 ORDER BY source, table_name
                """
            ).fetchall()

    # -------------------------------------------------------------- run log
    def start_run(
        self,
        run_id: str,
        layer: str,
        source: str | None = None,
        table_name: str | None = None,
        watermark_from: str | None = None,
    ) -> dt.datetime:
        started = utcnow()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO run_log
                    (run_id, layer, source, table_name, status, started_at, watermark_from)
                VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                [run_id, layer, source, table_name, started, watermark_from],
            )
        return started

    def finish_run(
        self,
        run_id: str,
        layer: str,
        *,
        status: str,
        rows: int = 0,
        table_name: str | None = None,
        watermark_to: str | None = None,
        message: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE run_log
                   SET status = ?, rows = ?, finished_at = ?, watermark_to = ?,
                       message = ?,
                       duration_s = date_diff('ms', started_at, ?) / 1000.0
                 WHERE run_id = ? AND layer = ?
                   AND (table_name = ? OR (table_name IS NULL AND ? IS NULL))
                   AND status = 'running'
                """,
                [
                    status,
                    rows,
                    (now := utcnow()),
                    watermark_to,
                    (message or "")[:2000] or None,
                    now,
                    run_id,
                    layer,
                    table_name,
                    table_name,
                ],
            )

    def recent_runs(self, limit: int = 20) -> list[tuple[Any, ...]]:
        with self.connect() as con:
            return con.execute(
                """
                SELECT started_at, run_id, layer, source, table_name, status,
                       rows, duration_s, message
                  FROM run_log
                 ORDER BY started_at DESC, layer
                 LIMIT ?
                """,
                [limit],
            ).fetchall()

    # -------------------------------------------------------------- qualidade
    def save_quality(self, run_id: str, results: list[dict[str, Any]]) -> None:
        if not results:
            return
        checked_at = utcnow()
        rows = [
            (
                run_id,
                checked_at,
                r.get("source"),
                r.get("table_name"),
                r.get("check_name"),
                r.get("column_name"),
                r.get("status"),
                None if r.get("observed") is None else str(r.get("observed")),
                r.get("details"),
            )
            for r in results
        ]
        with self.connect() as con:
            con.executemany(
                "INSERT INTO quality_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )

    def recent_quality(self, limit: int = 50) -> list[tuple[Any, ...]]:
        with self.connect() as con:
            return con.execute(
                """
                SELECT checked_at, source, table_name, check_name, column_name,
                       status, observed, details
                  FROM quality_results
                 ORDER BY checked_at DESC
                 LIMIT ?
                """,
                [limit],
            ).fetchall()
