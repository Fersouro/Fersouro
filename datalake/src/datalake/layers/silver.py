"""Camada silver: uma linha por chave, colunas normalizadas, pronta para consulta.

O que a silver faz sobre a bronze:
  * padroniza nomes de coluna para snake_case;
  * deduplica pela chave primaria mantendo a versao mais recente
    (``_ingested_at`` e, em empate, a propria coluna de watermark);
  * materializa um Parquet unico por tabela, sobrescrito de forma atomica.

Para logica especifica, crie ``sql/silver/<fonte>__<tabela>.sql`` usando o
marcador ``{{bronze}}`` no lugar da origem -- o arquivo substitui o SQL gerado.
"""

from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings, SourceConfig, TableConfig
from ..duck import connect, quote, quote_literal, snake_case
from ..logging_conf import get_logger
from ..state.control import ControlDB
from ..storage import paths

log = get_logger(__name__)

AUDIT_COLUMNS = ("_source", "_table", "_batch_id", "_ingested_at", "_ingest_date")


@dataclass
class SilverResult:
    source: str
    table: str
    status: str
    rows: int = 0
    duration_s: float = 0.0
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("success", "skipped")


def bronze_relation(
    settings: Settings, source: str, table: str, with_position: bool = False
) -> str:
    """Expressao read_parquet sobre toda a bronze da tabela.

    ``with_position`` acrescenta ``filename`` e ``file_row_number``, usados como
    ultimo criterio de desempate na deduplicacao.
    """
    glob = paths.glob_parquet(paths.bronze_table_dir(settings.root, source, table))
    extra = ", filename = true, file_row_number = true" if with_position else ""
    return (
        f"read_parquet({quote_literal(glob)}, hive_partitioning = true, "
        f"union_by_name = true{extra})"
    )


def has_bronze_data(settings: Settings, source: str, table: str) -> bool:
    directory = paths.bronze_table_dir(settings.root, source, table)
    return directory.exists() and any(directory.rglob("*.parquet"))


def custom_sql_path(settings: Settings, source: str, table: str) -> Path:
    return settings.sql_dir / "silver" / f"{source.lower()}__{table.lower()}.sql"


def _column_names(con, relation: str) -> list[str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    return [row[0] for row in rows]


def _projection(columns: list[str]) -> str:
    """Lista de selecao renomeando para snake_case sem colidir nomes."""
    used: set[str] = set()
    parts: list[str] = []
    for column in columns:
        if column.startswith("_"):  # colunas de auditoria mantem o nome
            alias = column
        else:
            alias = snake_case(column)
            base, counter = alias, 2
            while alias in used:
                alias = f"{base}_{counter}"
                counter += 1
        used.add(alias)
        parts.append(
            quote(column) if alias == column else f"{quote(column)} AS {quote(alias)}"
        )
    return ",\n       ".join(parts)


def build_sql(settings: Settings, source: str, table: TableConfig, con) -> str:
    """SQL que produz a silver da tabela."""
    custom = custom_sql_path(settings, source, table.key)
    relation = bronze_relation(settings, source, table.key)
    if custom.exists():
        log.info("[%s.%s] usando SQL customizado %s", source, table.key, custom.name)
        return custom.read_text(encoding="utf-8").replace("{{bronze}}", relation)

    columns = _column_names(con, relation)
    projection = _projection(columns)

    if not table.primary_key:
        # Sem chave nao da para deduplicar linha a linha: fica so a ultima carga.
        return f"""
SELECT {projection}
  FROM {relation}
 WHERE _batch_id = (SELECT max(_batch_id) FROM {relation})
""".strip()

    available = {c.upper(): c for c in columns}
    missing = [k for k in table.primary_key if k.upper() not in available]
    if missing:
        raise ValueError(
            f"[{source}.{table.name}] primary_key {missing} nao existe na bronze. "
            f"Colunas disponiveis: {', '.join(columns)}"
        )
    partition = ", ".join(quote(available[k.upper()]) for k in table.primary_key)

    order = ["_ingested_at DESC"]
    if table.watermark_column and table.watermark_column.upper() in available:
        order.insert(0, f"{quote(available[table.watermark_column.upper()])} DESC NULLS LAST")
    # Duas versoes da mesma chave no mesmo lote empatam em _ingested_at; sem um
    # criterio final a linha vencedora mudaria a cada execucao. A posicao fisica
    # (arquivo + linha) resolve o empate sempre do mesmo jeito: vence a ultima
    # linha lida da origem.
    order += ["filename DESC", "file_row_number DESC"]

    return f"""
SELECT {projection}
  FROM (
        SELECT *,
               row_number() OVER (
                   PARTITION BY {partition}
                   ORDER BY {', '.join(order)}
               ) AS _rn
          FROM {bronze_relation(settings, source, table.key, with_position=True)}
       )
 WHERE _rn = 1
""".strip()


def build_table(
    settings: Settings,
    source: SourceConfig,
    table: TableConfig,
    control: ControlDB,
    run_id: str,
) -> SilverResult:
    """Materializa a silver de uma tabela."""
    started = dt.datetime.now()
    if not has_bronze_data(settings, source.name, table.key):
        log.warning(
            "[%s.%s] sem dados na bronze: silver ignorada", source.name, table.name
        )
        return SilverResult(source.name, table.key, "skipped", message="bronze vazia")

    control.start_run(run_id, "silver", source.name, table.key)
    target = paths.silver_table_dir(settings.root, source.name, table.key)
    staging = target.with_name(f"{target.name}.staging-{run_id}")

    con = connect(settings)
    try:
        sql = build_sql(settings, source.name, table, con)
        staging.mkdir(parents=True, exist_ok=True)
        destination = staging / "data.parquet"
        con.execute(
            f"COPY ({sql}) TO {quote_literal(str(destination))} "
            f"(FORMAT PARQUET, COMPRESSION {settings.compression})"
        )
        rows = con.execute(
            f"SELECT count(*) FROM read_parquet({quote_literal(str(destination))})"
        ).fetchone()[0]
        paths.replace_dir(staging, target)

        duration = (dt.datetime.now() - started).total_seconds()
        control.finish_run(
            run_id, "silver", status="success", rows=rows, table_name=table.key
        )
        log.info(
            "[%s.%s] silver com %s linhas (%.1fs)",
            source.name,
            table.name,
            f"{rows:,}",
            duration,
        )
        return SilverResult(source.name, table.key, "success", rows, duration)

    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        control.finish_run(
            run_id,
            "silver",
            status="failed",
            table_name=table.key,
            message=f"{type(exc).__name__}: {exc}",
        )
        log.error("[%s.%s] silver falhou: %s", source.name, table.name, exc)
        return SilverResult(
            source.name,
            table.key,
            "failed",
            duration_s=(dt.datetime.now() - started).total_seconds(),
            message=f"{type(exc).__name__}: {exc}",
        )
    finally:
        con.close()


def build_source(
    settings: Settings,
    source: SourceConfig,
    control: ControlDB,
    run_id: str,
    tables: list[str] | None = None,
) -> list[SilverResult]:
    selected = [source.table(t) for t in tables] if tables else list(source.tables)
    return [build_table(settings, source, t, control, run_id) for t in selected]
