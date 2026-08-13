"""Layout fisico do lake.

    data/
      bronze/<fonte>/<tabela>/_ingest_date=YYYY-MM-DD/part-<batch_id>-000.parquet
      silver/<fonte>/<tabela>/data.parquet
      gold/<modelo>/data.parquet
      _control/control.duckdb
      lake.duckdb

Bronze e append-only e particionado por data de ingestao; silver e gold sao
sobrescritos de forma atomica (escreve em .tmp e troca o diretorio).
"""

from __future__ import annotations

import shutil
from pathlib import Path


def bronze_table_dir(root: Path, source: str, table: str) -> Path:
    return root / "bronze" / source.lower() / table.lower()


def bronze_partition_dir(root: Path, source: str, table: str, ingest_date: str) -> Path:
    return bronze_table_dir(root, source, table) / f"_ingest_date={ingest_date}"


def silver_table_dir(root: Path, source: str, table: str) -> Path:
    return root / "silver" / source.lower() / table.lower()


def gold_model_dir(root: Path, model: str) -> Path:
    return root / "gold" / model.lower()


def glob_parquet(directory: Path) -> str:
    """Padrao de leitura recursiva usado nas funcoes read_parquet do DuckDB."""
    return str(directory / "**" / "*.parquet")


def replace_dir(staging: Path, target: Path) -> None:
    """Troca ``target`` por ``staging`` com a menor janela possivel de inconsistencia."""
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(target.name + ".old")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
    except Exception:
        if backup.exists() and not target.exists():
            backup.rename(target)  # desfaz para nao deixar o dataset sumido
        raise
    if backup.exists():
        shutil.rmtree(backup)


def ensure_layout(root: Path) -> list[Path]:
    """Cria os diretorios base do lake e devolve a lista criada."""
    created = []
    for path in (
        root,
        root / "bronze",
        root / "silver",
        root / "gold",
        root / "_control",
    ):
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created
