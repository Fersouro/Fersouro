"""Introspeccao do dicionario de dados Oracle.

Serve para responder "o que existe nesse banco e como devo configurar?" sem
abrir o SQL Developer: lista os schemas acessiveis, as tabelas de um schema com
volume estimado, e propõe chave primaria e coluna de watermark de cada tabela.

O resultado vira um YAML pronto para colar em ``conf/sources/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .connectors.base import ConnectorError
from .duck import snake_case
from .logging_conf import get_logger

log = get_logger(__name__)

# Nomes tipicos de coluna de ultima alteracao, do melhor para o pior candidato.
WATERMARK_PATTERNS = (
    "DT_ATUALIZACAO",
    "DATA_ATUALIZACAO",
    "DT_ALTERACAO",
    "DATA_ALTERACAO",
    "DT_ULT_ALTERACAO",
    "UPDATED_AT",
    "LAST_UPDATE",
    "LAST_UPDATED",
    "DT_MODIFICACAO",
    "DT_UPDATE",
    "DT_CADASTRO",
    "DATA_CADASTRO",
    "CREATED_AT",
    "DT_INCLUSAO",
    "DT_EMISSAO",
)

DATE_TYPES = ("DATE", "TIMESTAMP")

# Acima disso, recarregar tudo todo dia deixa de ser barato.
FULL_LOAD_MAX_ROWS = 200_000


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    precision: int | None
    scale: int | None
    nullable: bool

    @property
    def is_date(self) -> bool:
        return self.data_type.startswith(DATE_TYPES)


@dataclass
class TableInfo:
    name: str
    num_rows: int | None
    columns: list[ColumnInfo] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)

    @property
    def watermark_candidates(self) -> list[str]:
        """Colunas de data que parecem marcar a ultima alteracao, em ordem."""
        dates = {c.name for c in self.columns if c.is_date}
        ranked = [p for p in WATERMARK_PATTERNS if p in dates]
        ranked += sorted(dates - set(ranked))
        return ranked

    @property
    def suggested_watermark(self) -> str | None:
        candidatos = self.watermark_candidates
        return candidatos[0] if candidatos else None

    @property
    def suggested_load_mode(self) -> str:
        """Incremental so faz sentido com watermark, chave e volume que justifique."""
        if not self.suggested_watermark or not self.primary_key:
            return "full"
        if self.num_rows is not None and self.num_rows <= FULL_LOAD_MAX_ROWS:
            return "full"
        return "incremental"

    @property
    def observacao(self) -> str:
        if not self.primary_key:
            return "sem PK declarada: informe primary_key na mao"
        if not self.suggested_watermark:
            return "sem coluna de data: so carga full"
        return ""


def list_schemas(connector: Any) -> list[tuple[str, int]]:
    """Schemas visiveis para o usuario conectado e quantas tabelas cada um tem."""
    connector.open()
    with connector._con.cursor() as cur:
        cur.execute(
            """
            SELECT owner, COUNT(*) AS qtd
              FROM all_tables
             GROUP BY owner
             ORDER BY qtd DESC, owner
            """
        )
        return [(row[0], int(row[1])) for row in cur.fetchall()]


def list_tables(
    connector: Any, owner: str, table_filter: str | None = None
) -> list[TableInfo]:
    """So os nomes e o volume estimado -- consulta barata, sem colunas nem PK."""
    connector.open()
    with connector._con.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, num_rows
              FROM all_tables
             WHERE owner = :owner AND table_name LIKE :padrao
             ORDER BY table_name
            """,
            {"owner": owner.upper(), "padrao": (table_filter or "%").upper()},
        )
        return [
            TableInfo(name=name, num_rows=None if rows is None else int(rows))
            for name, rows in cur.fetchall()
        ]


def select_tables(
    tables: list[TableInfo], top: int | None = None, min_rows: int | None = None
) -> list[TableInfo]:
    """Recorta a lista por volume: as maiores, ou as acima de um piso."""
    selecionadas = tables
    if min_rows is not None:
        selecionadas = [t for t in selecionadas if (t.num_rows or 0) >= min_rows]
    if top is not None:
        # num_rows nulo (sem estatistica coletada) vai para o fim da fila.
        selecionadas = sorted(
            selecionadas, key=lambda t: (t.num_rows is None, -(t.num_rows or 0), t.name)
        )[:top]
    return selecionadas


def _chunks(valores: list[str], tamanho: int = 500) -> list[list[str]]:
    """Oracle limita a lista IN em 1000 itens; 500 da folga com seguranca."""
    return [valores[i : i + tamanho] for i in range(0, len(valores), tamanho)]


def inspect_schema(
    connector: Any,
    owner: str,
    table_filter: str | None = None,
    top: int | None = None,
    min_rows: int | None = None,
) -> list[TableInfo]:
    """Le tabelas, colunas e chaves primarias de um schema.

    Em schema grande (milhares de tabelas), ler as colunas de tudo custa caro e
    quase sempre e desperdicio. Por isso o recorte por volume acontece antes de
    buscar coluna e chave: so o que sobra e detalhado.
    """
    owner = owner.upper()
    tables = list_tables(connector, owner, table_filter)
    if not tables:
        raise ConnectorError(
            f"Nenhuma tabela encontrada em '{owner}'"
            + (f" com o filtro '{table_filter}'." if table_filter else ".")
            + " Confira o nome do schema com 'datalake discover --schemas'."
        )

    selecionadas = {t.name: t for t in select_tables(tables, top, min_rows)}
    if not selecionadas:
        raise ConnectorError(
            f"O filtro de volume excluiu todas as {len(tables)} tabelas de '{owner}'. "
            f"Baixe o --min-rows ou aumente o --top."
        )

    nomes = list(selecionadas)
    with connector._con.cursor() as cur:
        for lote in _chunks(nomes):
            binds = {f"t{i}": nome for i, nome in enumerate(lote)}
            lista = ", ".join(f":{k}" for k in binds)
            binds["owner"] = owner

            cur.execute(
                f"""
                SELECT table_name, column_name, data_type, data_precision,
                       data_scale, nullable
                  FROM all_tab_columns
                 WHERE owner = :owner AND table_name IN ({lista})
                 ORDER BY table_name, column_id
                """,
                binds,
            )
            for table_name, column, tipo, precision, scale, nullable in cur.fetchall():
                selecionadas[table_name].columns.append(
                    ColumnInfo(
                        name=column,
                        data_type=tipo,
                        precision=None if precision is None else int(precision),
                        scale=None if scale is None else int(scale),
                        nullable=(nullable == "Y"),
                    )
                )

            cur.execute(
                f"""
                SELECT c.table_name, cc.column_name
                  FROM all_constraints c
                  JOIN all_cons_columns cc
                    ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name
                 WHERE c.owner = :owner
                   AND c.constraint_type = 'P'
                   AND c.table_name IN ({lista})
                 ORDER BY c.table_name, cc.position
                """,
                binds,
            )
            for table_name, column in cur.fetchall():
                selecionadas[table_name].primary_key.append(column)

    return list(selecionadas.values())


def to_yaml(source_name: str, owner: str, tables: list[TableInfo]) -> str:
    """Gera o YAML da fonte a partir do que foi descoberto."""
    linhas = [
        f"# Gerado por 'datalake discover -s {source_name} --schema {owner}'.",
        "# Revise antes de usar: o modo de carga e a coluna de watermark sao",
        "# sugestoes baseadas em nome e volume, nao em regra de negocio.",
        f"name: {source_name}",
        "type: oracle",
        "",
        "connection:",
        f"  dsn: ${{{source_name.upper()}_DSN}}",
        f"  user: ${{{source_name.upper()}_USER}}",
        f"  password: ${{{source_name.upper()}_PASSWORD}}",
        "  thick_mode: false",
        "",
        "defaults:",
        f"  schema: {owner}",
        "  batch_rows: 200000",
        "",
        "tables:",
    ]

    for table in sorted(tables, key=lambda t: t.name):
        volume = "desconhecido" if table.num_rows is None else f"{table.num_rows:,} linhas"
        linhas.append(f"  # {volume}")
        linhas.append(f"  - name: {table.name}")
        linhas.append(f"    load_mode: {table.suggested_load_mode}")

        if table.primary_key:
            linhas.append(f"    primary_key: [{', '.join(table.primary_key)}]")
        else:
            linhas.append("    # ATENCAO: tabela sem PK declarada no banco.")
            linhas.append("    # primary_key: [???]  <- preencha para deduplicar na silver")

        if table.suggested_load_mode == "incremental":
            linhas.append(f"    watermark_column: {table.suggested_watermark}")
            linhas.append("    watermark_type: timestamp")
            linhas.append("    lookback: 1")
        elif table.suggested_watermark:
            linhas.append(f"    # candidata a watermark: {table.suggested_watermark}")

        if table.primary_key:
            # Os testes de qualidade rodam sobre a silver, onde os nomes ja
            # estao em snake_case -- diferente de primary_key, que se refere as
            # colunas da origem.
            chave = [snake_case(c) for c in table.primary_key]
            obrigatorias = [snake_case(c.name) for c in table.columns if not c.nullable][:6]
            linhas.append("    quality:")
            linhas.append(f"      unique: [{', '.join(chave)}]")
            if obrigatorias:
                linhas.append(f"      not_null: [{', '.join(obrigatorias)}]")
        linhas.append("")

    return "\n".join(linhas)
