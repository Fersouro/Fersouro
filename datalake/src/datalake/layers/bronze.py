"""Camada bronze: copia fiel da origem, particionada por data de ingestao.

Regras:
  * nada e transformado -- so entram as colunas de auditoria (``_source``,
    ``_table``, ``_batch_id``, ``_ingested_at``);
  * a carga escreve num diretorio temporario e so promove os arquivos no fim,
    entao uma falha no meio nao deixa carga parcial visivel;
  * carga ``full`` substitui a particao do dia (rerodar nao duplica);
    carga ``incremental`` acrescenta arquivos a particao do dia.
"""

from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings, SourceConfig, TableConfig
from ..connectors.base import Connector
from ..logging_conf import get_logger
from ..state import watermark as wm
from ..state.control import ControlDB
from ..storage import paths
from ..storage.writer import ParquetBatchWriter, add_audit_columns
from ..storage.writer import WriteResult  # noqa: F401  (reexport util em testes)

log = get_logger(__name__)


@dataclass
class IngestResult:
    source: str
    table: str
    status: str
    rows: int = 0
    files: int = 0
    bytes_written: int = 0
    watermark_from: str | None = None
    watermark_to: str | None = None
    duration_s: float = 0.0
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("success", "skipped")


def resolve_since(
    table: TableConfig, control: ControlDB, source_name: str, full: bool
) -> tuple[Any, str | None]:
    """Watermark inicial da carga (ja com lookback) e o valor bruto armazenado."""
    if full or table.load_mode == "full":
        return None, None
    stored = control.get_watermark(source_name, table.key)
    if stored is None:
        log.info(
            "[%s.%s] sem watermark registrado: primeira carga sera total",
            source_name,
            table.name,
        )
        return None, None
    value = wm.deserialize(stored, table.watermark_type)
    return wm.apply_lookback(value, table.lookback, table.watermark_type), stored


def ingest_table(
    settings: Settings,
    source: SourceConfig,
    table: TableConfig,
    connector: Connector,
    control: ControlDB,
    run_id: str,
    *,
    full: bool = False,
    dry_run: bool = False,
) -> IngestResult:
    """Extrai uma tabela da origem e grava na bronze."""
    started = dt.datetime.now()
    since, stored_wm = resolve_since(table, control, source.name, full)
    mode = "full" if since is None else "incremental"
    ingest_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    partition = paths.bronze_partition_dir(
        settings.root, source.name, table.key, ingest_date
    )
    staging = partition.with_name(f"{partition.name}.staging-{run_id}")

    if dry_run:
        total = connector.count(table, since)
        log.info(
            "[%s.%s] dry-run: %s linhas seriam extraidas (modo %s, since=%s)",
            source.name,
            table.name,
            "?" if total is None else f"{total:,}",
            mode,
            since,
        )
        return IngestResult(
            source=source.name,
            table=table.key,
            status="skipped",
            rows=total or 0,
            watermark_from=stored_wm,
            message="dry-run",
        )

    control.start_run(run_id, "bronze", source.name, table.key, stored_wm)
    writer = ParquetBatchWriter(
        staging, prefix=f"part-{run_id}", compression=settings.compression
    )
    max_wm: Any = None

    try:
        for batch in connector.extract(table, since):
            if table.watermark_column and batch.num_rows:
                max_wm = wm.max_of(
                    max_wm, wm.max_from_arrow(batch, table.watermark_column)
                )
            enriched = add_audit_columns(batch, source.name, table.key, run_id)
            if writer.schema is None:
                writer.schema = enriched.schema
            writer.write(enriched)

        rows = writer.result.rows
        size = writer.result.bytes_written
        _commit(staging, partition, replace=(mode == "full"))

        new_wm = wm.serialize(max_wm) or stored_wm
        control.save_state(
            source.name,
            table.key,
            watermark_value=new_wm,
            watermark_type=table.watermark_type if table.watermark_column else None,
            run_id=run_id,
            status="success",
            rows=rows,
        )
        duration = (dt.datetime.now() - started).total_seconds()
        control.finish_run(
            run_id,
            "bronze",
            status="success",
            rows=rows,
            table_name=table.key,
            watermark_to=new_wm,
        )
        log.info(
            "[%s.%s] %s linhas em %s arquivo(s), %.1f MB, %.1fs (modo %s)%s",
            source.name,
            table.name,
            f"{rows:,}",
            len(writer.result.files),
            size / 1_048_576,
            duration,
            mode,
            f", watermark -> {new_wm}" if new_wm else "",
        )
        return IngestResult(
            source=source.name,
            table=table.key,
            status="success",
            rows=rows,
            files=len(writer.result.files),
            bytes_written=size,
            watermark_from=stored_wm,
            watermark_to=new_wm,
            duration_s=duration,
        )

    except Exception as exc:  # noqa: BLE001 - a falha de uma tabela nao derruba o lote
        writer.rollback()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        duration = (dt.datetime.now() - started).total_seconds()
        control.finish_run(
            run_id,
            "bronze",
            status="failed",
            table_name=table.key,
            message=f"{type(exc).__name__}: {exc}",
        )
        log.error("[%s.%s] falhou: %s", source.name, table.name, exc)
        return IngestResult(
            source=source.name,
            table=table.key,
            status="failed",
            watermark_from=stored_wm,
            duration_s=duration,
            message=f"{type(exc).__name__}: {exc}",
        )


def _commit(staging: Path, partition: Path, replace: bool) -> None:
    """Promove os arquivos do diretorio temporario para a particao definitiva."""
    if not staging.exists():
        staging.mkdir(parents=True, exist_ok=True)
    if replace:
        paths.replace_dir(staging, partition)
        return
    partition.mkdir(parents=True, exist_ok=True)
    for file in sorted(staging.iterdir()):
        target = partition / file.name
        if target.exists():
            target.unlink()
        file.rename(target)
    shutil.rmtree(staging, ignore_errors=True)


def ingest_source(
    settings: Settings,
    source: SourceConfig,
    control: ControlDB,
    run_id: str,
    *,
    tables: list[str] | None = None,
    full: bool = False,
    dry_run: bool = False,
) -> list[IngestResult]:
    """Ingere todas as tabelas (ou as informadas) de uma fonte, reusando a conexao."""
    from ..connectors.registry import get_connector

    selected = (
        [source.table(name) for name in tables] if tables else list(source.tables)
    )
    if not selected:
        log.warning(
            "[%s] nenhuma tabela configurada: fonte ignorada. "
            "Rode 'datalake discover -s %s --schema <SCHEMA>' para descobrir o que existe.",
            source.name,
            source.name,
        )
        return []

    results: list[IngestResult] = []

    connector = get_connector(source, settings)
    try:
        connector.open()
        log.info("Origem: %s", connector.describe())
        for table in selected:
            results.append(
                ingest_table(
                    settings,
                    source,
                    table,
                    connector,
                    control,
                    run_id,
                    full=full,
                    dry_run=dry_run,
                )
            )
    finally:
        connector.close()
    return results
