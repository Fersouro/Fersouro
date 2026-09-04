"""Camada gold: modelos de negocio definidos em SQL puro.

Cada arquivo em ``sql/gold/*.sql`` vira um dataset. Antes de executar, o motor
registra uma view para cada tabela da silver:

    <fonte>__<tabela>   sempre
    <tabela>            quando o nome nao se repete entre as fontes

Modelos ja construidos na mesma execucao tambem viram view, entao um arquivo
pode usar outro como insumo. A ordem e alfabetica -- prefixe com numeros
(``10_dim_cliente.sql``, ``20_fato_vendas.sql``) quando houver dependencia.
"""

from __future__ import annotations

import datetime as dt
import re
import shutil

import duckdb
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..duck import connect, quote, quote_literal
from ..logging_conf import get_logger
from ..state.control import ControlDB
from ..storage import paths

log = get_logger(__name__)

_ORDER_PREFIX = re.compile(r"^\d+[-_]")


@dataclass
class GoldResult:
    model: str
    status: str
    rows: int = 0
    duration_s: float = 0.0
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("success", "skipped")


def model_name(path: Path) -> str:
    return _ORDER_PREFIX.sub("", path.stem).lower()


def list_models(settings: Settings) -> list[Path]:
    directory = settings.sql_dir / "gold"
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.sql") if not p.name.startswith("_"))


def silver_datasets(settings: Settings) -> dict[str, Path]:
    """Mapa ``fonte__tabela`` -> diretorio da silver."""
    found: dict[str, Path] = {}
    silver_root = settings.silver
    if not silver_root.is_dir():
        return found
    for source_dir in sorted(p for p in silver_root.iterdir() if p.is_dir()):
        for table_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            if any(table_dir.glob("*.parquet")):
                found[f"{source_dir.name}__{table_dir.name}"] = table_dir
    return found


def register_silver_views(con, settings: Settings) -> list[str]:
    """Cria as views da silver e devolve os nomes registrados."""
    datasets = silver_datasets(settings)
    names: list[str] = []

    short_counts: dict[str, int] = {}
    for full in datasets:
        short = full.split("__", 1)[1]
        short_counts[short] = short_counts.get(short, 0) + 1

    for full, directory in datasets.items():
        relation = f"read_parquet({quote_literal(paths.glob_parquet(directory))})"
        con.execute(f"CREATE OR REPLACE VIEW {quote(full)} AS SELECT * FROM {relation}")
        names.append(full)
        short = full.split("__", 1)[1]
        if short_counts[short] == 1:
            con.execute(
                f"CREATE OR REPLACE VIEW {quote(short)} AS SELECT * FROM {relation}"
            )
            names.append(short)
    return names


def build_model(
    settings: Settings, path: Path, control: ControlDB, run_id: str, con=None
) -> GoldResult:
    """Executa um arquivo SQL e materializa o resultado na gold."""
    name = model_name(path)
    started = dt.datetime.now()
    own_connection = con is None
    if own_connection:
        con = connect(settings)
        register_silver_views(con, settings)

    control.start_run(run_id, "gold", table_name=name)
    target = paths.gold_model_dir(settings.root, name)
    staging = target.with_name(f"{target.name}.staging-{run_id}")

    try:
        sql = path.read_text(encoding="utf-8").strip().rstrip(";")
        if not sql:
            raise ValueError(f"{path.name} esta vazio")
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

        # Disponibiliza o modelo para os proximos arquivos da mesma execucao.
        con.execute(
            f"CREATE OR REPLACE VIEW {quote(name)} AS SELECT * FROM "
            f"read_parquet({quote_literal(paths.glob_parquet(target))})"
        )

        duration = (dt.datetime.now() - started).total_seconds()
        control.finish_run(run_id, "gold", status="success", rows=rows, table_name=name)
        log.info("[gold.%s] %s linhas (%.1fs)", name, f"{rows:,}", duration)
        return GoldResult(name, "success", rows, duration)

    except duckdb.CatalogException as exc:
        # O modelo cita um objeto que a silver ainda nao tem. Num lake com varias
        # fontes isso e rotina -- carregou uma, a outra ainda nao -- e tratar como
        # falha faria a execucao inteira parecer quebrada.
        shutil.rmtree(staging, ignore_errors=True)
        faltante = str(exc).split("\n")[0]
        control.finish_run(
            run_id, "gold", status="skipped", table_name=name, message=faltante
        )
        log.warning("[gold.%s] ignorado: depende de objeto ausente na silver", name)
        return GoldResult(
            name,
            "skipped",
            duration_s=(dt.datetime.now() - started).total_seconds(),
            message="depende de objeto ainda nao carregado",
        )

    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        control.finish_run(
            run_id,
            "gold",
            status="failed",
            table_name=name,
            message=f"{type(exc).__name__}: {exc}",
        )
        log.error("[gold.%s] falhou: %s", name, exc)
        return GoldResult(
            name,
            "failed",
            duration_s=(dt.datetime.now() - started).total_seconds(),
            message=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if own_connection:
            con.close()


def build_all(
    settings: Settings, control: ControlDB, run_id: str, only: list[str] | None = None
) -> list[GoldResult]:
    models = list_models(settings)
    if only:
        wanted = {m.lower() for m in only}
        models = [p for p in models if model_name(p) in wanted]
        unknown = wanted - {model_name(p) for p in models}
        if unknown:
            raise ValueError(f"Modelo gold inexistente: {', '.join(sorted(unknown))}")
    if not models:
        log.warning("Nenhum modelo em %s", settings.sql_dir / "gold")
        return []

    con = connect(settings)
    try:
        views = register_silver_views(con, settings)
        log.info("Views da silver registradas: %s", ", ".join(views) or "(nenhuma)")
        return [build_model(settings, path, control, run_id, con) for path in models]
    finally:
        con.close()
