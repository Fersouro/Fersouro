"""Fixtures: monta um projeto datalake completo em diretorio temporario."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

SETTINGS_YML = """
lake:
  root: ./data
  control_db: ./data/_control/control.duckdb
  catalog_db: ./data/lake.duckdb
runtime:
  batch_rows: 1000
  arraysize: 500
  compression: zstd
  duckdb_memory_limit: 1GB
  duckdb_threads: 2
logging:
  level: WARNING
  dir: ./logs
"""

SOURCE_YML = """
name: erp
type: duckdb
connection:
  database: ./origem.duckdb
defaults:
  schema: main
tables:
  - name: clientes
    load_mode: full
    primary_key: [id_cliente]
    quality:
      not_null: [id_cliente, nome]
      unique: [id_cliente]
      row_count_min: 1
  - name: pedidos
    load_mode: incremental
    primary_key: [id_pedido]
    watermark_column: dt_atualizacao
    watermark_type: timestamp
    quality:
      not_null: [id_pedido]
      unique: [id_pedido]
"""

GOLD_SQL = """
SELECT p.id_pedido, p.id_cliente, c.nome, p.vlr_total
  FROM pedidos p
  LEFT JOIN clientes c ON c.id_cliente = p.id_cliente
 WHERE p.situacao <> 'C'
"""

BASE = dt.datetime(2026, 1, 10, 8, 0, 0)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Projeto com settings, uma fonte DuckDB e um modelo gold."""
    (tmp_path / "conf" / "sources").mkdir(parents=True)
    (tmp_path / "sql" / "gold").mkdir(parents=True)
    (tmp_path / "conf" / "settings.yml").write_text(SETTINGS_YML, encoding="utf-8")
    (tmp_path / "conf" / "sources" / "erp.yml").write_text(SOURCE_YML, encoding="utf-8")
    (tmp_path / "sql" / "gold" / "10_pedidos_cliente.sql").write_text(
        GOLD_SQL, encoding="utf-8"
    )

    con = duckdb.connect(str(tmp_path / "origem.duckdb"))
    con.execute(
        """
        CREATE TABLE clientes (
            id_cliente BIGINT, nome VARCHAR, uf VARCHAR
        );
        CREATE TABLE pedidos (
            id_pedido BIGINT, id_cliente BIGINT, situacao VARCHAR,
            vlr_total DECIMAL(18,2), dt_atualizacao TIMESTAMP
        );
        """
    )
    con.executemany(
        "INSERT INTO clientes VALUES (?, ?, ?)",
        [(1, "Alfa", "MG"), (2, "Beta", "SP"), (3, "Gama", "RJ")],
    )
    con.executemany(
        "INSERT INTO pedidos VALUES (?, ?, ?, ?, ?)",
        [
            (10, 1, "A", 100.00, BASE),
            (11, 2, "F", 250.50, BASE + dt.timedelta(minutes=5)),
            (12, 3, "C", 90.00, BASE + dt.timedelta(minutes=10)),
        ],
    )
    con.close()
    return tmp_path


@pytest.fixture
def settings(project: Path):
    from datalake.config import load_settings

    return load_settings(project)


@pytest.fixture
def control(settings):
    from datalake.state.control import ControlDB

    return ControlDB(settings.control_db)


def source_connection(project: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(project / "origem.duckdb"))
