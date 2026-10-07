"""Testes de qualidade declarados no YAML da fonte.

Exemplo::

    quality:
      severity: error          # error (padrao) faz o comando falhar; warn so avisa
      not_null: [id_pedido, dt_pedido]
      unique: [id_pedido]                 # lista simples = chave composta
      unique: [[id_pedido], [nr_nota]]    # lista de listas = varias chaves
      row_count_min: 1
      accepted_values:
        situacao: [A, C, X]
      freshness:
        column: dt_atualizacao
        max_age_hours: 26
      custom:
        - name: valor_nao_negativo
          sql: SELECT count(*) FROM {{silver}} WHERE vlr_total < 0

Em ``custom``, o SQL deve retornar um unico numero e a expectativa e zero.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, SourceConfig, TableConfig
from ..duck import connect, quote, quote_literal
from ..logging_conf import get_logger
from ..storage import paths

log = get_logger(__name__)

PASS, FAIL, ERROR = "pass", "fail", "error"


@dataclass
class QualityCheckResult:
    source: str
    table_name: str
    check_name: str
    status: str
    column_name: str | None = None
    observed: Any = None
    details: str | None = None
    severity: str = "error"

    @property
    def blocking(self) -> bool:
        return self.status in (FAIL, ERROR) and self.severity == "error"

    def as_row(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "table_name": self.table_name,
            "check_name": self.check_name,
            "column_name": self.column_name,
            "status": self.status,
            "observed": self.observed,
            "details": self.details,
        }


@dataclass
class _Context:
    source: str
    table: str
    relation: str
    severity: str
    columns: set[str]
    results: list[QualityCheckResult] = field(default_factory=list)

    def add(self, **kwargs: Any) -> None:
        self.results.append(
            QualityCheckResult(
                source=self.source,
                table_name=self.table,
                severity=self.severity,
                **kwargs,
            )
        )

    def missing_column(self, check: str, column: str) -> bool:
        if column.lower() in self.columns:
            return False
        self.add(
            check_name=check,
            column_name=column,
            status=ERROR,
            details=f"coluna '{column}' nao existe na silver",
        )
        return True


def run_table_checks(
    settings: Settings, source: SourceConfig, table: TableConfig
) -> list[QualityCheckResult]:
    """Roda os testes declarados para uma tabela. Sem 'quality', nao roda nada."""
    rules = dict(table.quality or {})
    if not rules:
        return []

    directory = paths.silver_table_dir(settings.root, source.name, table.key)
    if not any(directory.glob("*.parquet")):
        return [
            QualityCheckResult(
                source=source.name,
                table_name=table.key,
                check_name="silver_exists",
                status=ERROR,
                details=f"silver ausente em {directory}",
                severity=str(rules.get("severity", "error")),
            )
        ]

    relation = f"read_parquet({quote_literal(paths.glob_parquet(directory))})"
    con = connect(settings)
    try:
        columns = {
            row[0].lower()
            for row in con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
        }
        ctx = _Context(
            source=source.name,
            table=table.key,
            relation=relation,
            severity=str(rules.pop("severity", "error")).lower(),
            columns=columns,
        )
        _not_null(con, ctx, rules.get("not_null"))
        _unique(con, ctx, rules.get("unique"))
        _row_count_min(con, ctx, rules.get("row_count_min"))
        _accepted_values(con, ctx, rules.get("accepted_values"))
        _freshness(con, ctx, rules.get("freshness"))
        _custom(con, ctx, rules.get("custom"))
        return ctx.results
    finally:
        con.close()


def _not_null(con, ctx: _Context, columns: Any) -> None:
    for column in columns or []:
        if ctx.missing_column("not_null", column):
            continue
        nulls = con.execute(
            f"SELECT count(*) FROM {ctx.relation} WHERE {quote(column)} IS NULL"
        ).fetchone()[0]
        ctx.add(
            check_name="not_null",
            column_name=column,
            status=PASS if nulls == 0 else FAIL,
            observed=nulls,
            details=None if nulls == 0 else f"{nulls} linha(s) com nulo",
        )


def _unique(con, ctx: _Context, spec: Any) -> None:
    if not spec:
        return
    keys = spec if any(isinstance(item, (list, tuple)) for item in spec) else [spec]
    for key in keys:
        key = [key] if isinstance(key, str) else list(key)
        if any(ctx.missing_column("unique", c) for c in key):
            continue
        columns = ", ".join(quote(c) for c in key)
        duplicated = con.execute(
            f"""
            SELECT coalesce(sum(n - 1), 0)
              FROM (SELECT count(*) AS n FROM {ctx.relation} GROUP BY {columns})
             WHERE n > 1
            """
        ).fetchone()[0]
        ctx.add(
            check_name="unique",
            column_name=", ".join(key),
            status=PASS if duplicated == 0 else FAIL,
            observed=duplicated,
            details=None if duplicated == 0 else f"{duplicated} linha(s) duplicada(s)",
        )


def _row_count_min(con, ctx: _Context, minimum: Any) -> None:
    if minimum is None:
        return
    total = con.execute(f"SELECT count(*) FROM {ctx.relation}").fetchone()[0]
    ctx.add(
        check_name="row_count_min",
        status=PASS if total >= int(minimum) else FAIL,
        observed=total,
        details=None if total >= int(minimum) else f"esperado >= {minimum}",
    )


def _accepted_values(con, ctx: _Context, mapping: Any) -> None:
    for column, values in (mapping or {}).items():
        if ctx.missing_column("accepted_values", column):
            continue
        allowed = ", ".join(quote_literal(str(v)) for v in values)
        invalid = con.execute(
            f"""
            SELECT count(*) FROM {ctx.relation}
             WHERE {quote(column)} IS NOT NULL
               AND CAST({quote(column)} AS VARCHAR) NOT IN ({allowed})
            """
        ).fetchone()[0]
        ctx.add(
            check_name="accepted_values",
            column_name=column,
            status=PASS if invalid == 0 else FAIL,
            observed=invalid,
            details=None if invalid == 0 else f"{invalid} linha(s) fora de [{allowed}]",
        )


def _freshness(con, ctx: _Context, spec: Any) -> None:
    if not spec:
        return
    column = spec.get("column")
    max_age = float(spec.get("max_age_hours", 24))
    if not column or ctx.missing_column("freshness", column):
        return
    newest = con.execute(
        f"SELECT max(CAST({quote(column)} AS TIMESTAMP)) FROM {ctx.relation}"
    ).fetchone()[0]
    if newest is None:
        ctx.add(
            check_name="freshness",
            column_name=column,
            status=FAIL,
            details="nenhum valor de data na coluna",
        )
        return
    age = (dt.datetime.now() - newest).total_seconds() / 3600
    ctx.add(
        check_name="freshness",
        column_name=column,
        status=PASS if age <= max_age else FAIL,
        observed=f"{age:.1f}h",
        details=None if age <= max_age else f"dado mais novo tem {age:.1f}h (limite {max_age}h)",
    )


def _custom(con, ctx: _Context, checks: Any) -> None:
    for index, check in enumerate(checks or [], start=1):
        name = check.get("name") or f"custom_{index}"
        sql = (check.get("sql") or "").replace("{{silver}}", ctx.relation)
        if not sql.strip():
            ctx.add(check_name=name, status=ERROR, details="teste sem 'sql'")
            continue
        try:
            observed = con.execute(sql).fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            ctx.add(check_name=name, status=ERROR, details=str(exc))
            continue
        failed = bool(observed)
        ctx.add(
            check_name=name,
            status=FAIL if failed else PASS,
            observed=observed,
            details=None if not failed else f"{observed} ocorrencia(s)",
        )


def summarize(results: list[QualityCheckResult]) -> tuple[int, int, int]:
    """Contagem (aprovados, reprovados, erros)."""
    passed = sum(1 for r in results if r.status == PASS)
    failed = sum(1 for r in results if r.status == FAIL)
    errors = sum(1 for r in results if r.status == ERROR)
    return passed, failed, errors
