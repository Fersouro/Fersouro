"""Monta o arquivo lake.duckdb com views sobre silver e gold.

O arquivo e so um catalogo: nenhum dado e copiado, cada view aponta para os
Parquet do lake. Consumo:

    duckdb data/lake.duckdb -c "SELECT * FROM gold.fato_vendas LIMIT 10"

No Power BI, use o driver ODBC do DuckDB apontando para esse arquivo ou leia a
pasta ``data/gold`` direto pelo conector Parquet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..duck import connect, quote, quote_literal
from ..logging_conf import get_logger
from ..storage import paths

log = get_logger(__name__)


@dataclass
class CatalogEntry:
    schema: str
    name: str
    rows: int
    location: Path


def _datasets(root: Path, layer: str) -> dict[str, Path]:
    """Diretorios com Parquet dentro de uma camada, achatando fonte/tabela."""
    found: dict[str, Path] = {}
    layer_root = root / layer
    if not layer_root.is_dir():
        return found
    for first in sorted(p for p in layer_root.iterdir() if p.is_dir()):
        if any(first.glob("*.parquet")):  # gold/<modelo>/
            found[first.name] = first
            continue
        for second in sorted(p for p in first.iterdir() if p.is_dir()):  # silver/<f>/<t>/
            if any(second.glob("*.parquet")):
                found[f"{first.name}__{second.name}"] = second
    return found


def build_catalog(settings: Settings) -> list[CatalogEntry]:
    """Recria as views de silver e gold no catalogo e devolve o inventario."""
    entries: list[CatalogEntry] = []
    con = connect(settings, settings.catalog_db)
    try:
        for layer in ("silver", "gold"):
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {quote(layer)}")
            existing = {
                row[0]
                for row in con.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                    [layer],
                ).fetchall()
            }
            datasets = _datasets(settings.root, layer)
            for name, directory in datasets.items():
                relation = f"read_parquet({quote_literal(paths.glob_parquet(directory))})"
                con.execute(
                    f"CREATE OR REPLACE VIEW {quote(layer)}.{quote(name)} AS "
                    f"SELECT * FROM {relation}"
                )
                rows = con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
                entries.append(CatalogEntry(layer, name, rows, directory))
            # Remove views orfas de datasets que nao existem mais.
            for orphan in existing - set(datasets):
                con.execute(f"DROP VIEW IF EXISTS {quote(layer)}.{quote(orphan)}")
                log.info("View removida: %s.%s", layer, orphan)

        con.execute(
            """
            CREATE OR REPLACE VIEW lake_objects AS
            SELECT table_schema AS camada, table_name AS objeto
              FROM information_schema.tables
             WHERE table_schema IN ('silver', 'gold')
             ORDER BY 1, 2
            """
        )
    finally:
        con.close()

    log.info(
        "Catalogo atualizado em %s (%s objetos)", settings.catalog_db, len(entries)
    )
    return entries
