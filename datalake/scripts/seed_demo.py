#!/usr/bin/env python3
"""Gera (ou atualiza) a base DuckDB de demonstracao usada pela fonte demo_erp.

    python scripts/seed_demo.py                 # cria do zero
    python scripts/seed_demo.py --novos 200     # simula movimento novo/alterado

O segundo comando serve para conferir a carga incremental: rode
``datalake run``, depois ``--novos``, depois ``datalake run`` de novo e compare
a contagem de linhas por execucao em ``datalake state``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "_demo" / "erp.duckdb"

UFS = ["MG", "SP", "RJ", "RS", "PR", "BA", "SC", "GO", "PE", "CE"]
NOMES = ["Comercial", "Industria", "Distribuidora", "Atacado", "Servicos", "Transportes"]
SOBRENOMES = ["Souza", "Roquete", "Andrade", "Lima", "Pereira", "Costa", "Martins"]
PRODUTOS = list(range(1, 51))

SCHEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id_cliente      BIGINT PRIMARY KEY,
    nome            VARCHAR,
    uf              VARCHAR,
    situacao        VARCHAR,
    dt_cadastro     DATE,
    limite_credito  DECIMAL(18,2)
);
CREATE TABLE IF NOT EXISTS pedidos (
    id_pedido       BIGINT PRIMARY KEY,
    id_cliente      BIGINT,
    dt_pedido       DATE,
    situacao        VARCHAR,
    vlr_total       DECIMAL(18,2),
    dt_atualizacao  TIMESTAMP
);
CREATE TABLE IF NOT EXISTS itens_pedido (
    id_pedido       BIGINT,
    nr_item         INTEGER,
    id_produto      BIGINT,
    quantidade      DECIMAL(18,4),
    vlr_unitario    DECIMAL(18,4),
    dt_atualizacao  TIMESTAMP,
    PRIMARY KEY (id_pedido, nr_item)
);
"""


def _random_client(client_id: int, rng: random.Random) -> tuple:
    nome = f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)} {client_id:04d}"
    cadastro = dt.date(2019, 1, 1) + dt.timedelta(days=rng.randint(0, 2200))
    return (
        client_id,
        nome,
        rng.choice(UFS),
        "A" if rng.random() > 0.12 else "I",
        cadastro,
        round(rng.uniform(1_000, 250_000), 2),
    )


def _random_order(order_id: int, clientes: int, rng: random.Random, now: dt.datetime) -> tuple:
    dias = rng.randint(0, 540)
    data = (now - dt.timedelta(days=dias)).date()
    atualizado = now - dt.timedelta(days=dias, minutes=rng.randint(0, 1440))
    return (
        order_id,
        rng.randint(1, clientes),
        data,
        rng.choice(["A", "F", "F", "F", "C"]),
        0.0,  # recalculado a partir dos itens
        atualizado,
    )


def _random_items(order_id: int, rng: random.Random, atualizado: dt.datetime) -> list[tuple]:
    return [
        (
            order_id,
            item,
            rng.choice(PRODUTOS),
            round(rng.uniform(1, 40), 4),
            round(rng.uniform(5, 3_000), 4),
            atualizado,
        )
        for item in range(1, rng.randint(1, 6) + 1)
    ]


def seed(clientes: int, pedidos: int, seed_value: int) -> None:
    rng = random.Random(seed_value)
    now = dt.datetime.now().replace(microsecond=0)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("DROP TABLE IF EXISTS itens_pedido")
        con.execute("DROP TABLE IF EXISTS pedidos")
        con.execute("DROP TABLE IF EXISTS clientes")
        con.execute(SCHEMA)

        con.executemany(
            "INSERT INTO clientes VALUES (?, ?, ?, ?, ?, ?)",
            [_random_client(i, rng) for i in range(1, clientes + 1)],
        )

        orders = [_random_order(i, clientes, rng, now) for i in range(1, pedidos + 1)]
        items: list[tuple] = []
        for order in orders:
            items.extend(_random_items(order[0], rng, order[5]))
        con.executemany("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?)", orders)
        con.executemany("INSERT INTO itens_pedido VALUES (?, ?, ?, ?, ?, ?)", items)
        _recalc_totais(con)

        print(f"Base criada em {DB_PATH}")
        _resumo(con)
    finally:
        con.close()


def novos(quantidade: int, seed_value: int) -> None:
    """Insere pedidos novos e altera alguns existentes (testa o incremental)."""
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} nao existe. Rode sem --novos primeiro.")
    rng = random.Random(seed_value)
    now = dt.datetime.now().replace(microsecond=0)
    con = duckdb.connect(str(DB_PATH))
    try:
        max_pedido = con.execute("SELECT coalesce(max(id_pedido), 0) FROM pedidos").fetchone()[0]
        total_clientes = con.execute("SELECT count(*) FROM clientes").fetchone()[0]

        orders, items = [], []
        for offset in range(1, quantidade + 1):
            order_id = max_pedido + offset
            order = (
                order_id,
                rng.randint(1, total_clientes),
                now.date(),
                "A",
                0.0,
                now,
            )
            orders.append(order)
            items.extend(_random_items(order_id, rng, now))
        con.executemany("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?)", orders)
        con.executemany("INSERT INTO itens_pedido VALUES (?, ?, ?, ?, ?, ?)", items)

        alterados = max(1, quantidade // 4)
        con.execute(
            """
            UPDATE pedidos SET situacao = 'F', dt_atualizacao = ?
             WHERE id_pedido IN (
                 SELECT id_pedido FROM pedidos WHERE situacao = 'A' AND id_pedido <= ?
                 LIMIT ?
             )
            """,
            [now, max_pedido, alterados],
        )
        _recalc_totais(con)
        print(f"{quantidade} pedido(s) novo(s) e ate {alterados} alterado(s) em {DB_PATH}")
        _resumo(con)
    finally:
        con.close()


def _recalc_totais(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        UPDATE pedidos p
           SET vlr_total = coalesce((
                   SELECT round(sum(i.quantidade * i.vlr_unitario), 2)
                     FROM itens_pedido i
                    WHERE i.id_pedido = p.id_pedido
               ), 0)
        """
    )


def _resumo(con: duckdb.DuckDBPyConnection) -> None:
    for table in ("clientes", "pedidos", "itens_pedido"):
        total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:<14} {total:>8,} linhas")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clientes", type=int, default=500)
    parser.add_argument("--pedidos", type=int, default=5000)
    parser.add_argument("--novos", type=int, help="so acrescenta movimento novo")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.novos:
        novos(args.novos, args.seed)
    else:
        seed(args.clientes, args.pedidos, args.seed)


if __name__ == "__main__":
    main()
