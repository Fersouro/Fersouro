"""Conector Oracle baseado em python-oracledb.

Usa o modo *thin* por padrao (nao exige Oracle Instant Client). O modo *thick* so
e necessario para tnsnames.ora, wallet ou charsets legados.

A extracao monta um schema Arrow explicito a partir do ``cursor.description``
antes de ler qualquer linha. Sem isso, lotes diferentes da mesma tabela poderiam
inferir tipos diferentes (uma pagina toda nula vira ``null``, a seguinte vira
``string``) e o Parquet resultante ficaria inconsistente.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Sequence

import pyarrow as pa

from ..config import TableConfig, require_resolved
from ..logging_conf import get_logger
from .base import Connector, ConnectorError
from .registry import register_connector

log = get_logger(__name__)

# Identificadores vem do YAML (confiavel), mas validar evita erro de digitacao
# virando SQL quebrado -- ou pior, SQL valido e inesperado.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")

_MAX_PRECISION = 38


def _check_identifier(name: str, what: str) -> str:
    if not _IDENTIFIER.match(name or ""):
        raise ConnectorError(
            f"{what} invalido: '{name}'. Use apenas letras, numeros e _ $ #"
        )
    return name


def _parse_type_override(spec: str) -> pa.DataType:
    """Converte 'decimal(18,4)', 'string', 'int64'... em um tipo Arrow."""
    text = spec.strip().lower()
    match = re.fullmatch(r"decimal\s*\(\s*(\d+)\s*,\s*(-?\d+)\s*\)", text)
    if match:
        return pa.decimal128(int(match.group(1)), int(match.group(2)))
    simple: dict[str, pa.DataType] = {
        "string": pa.string(),
        "varchar": pa.string(),
        "text": pa.string(),
        "int": pa.int64(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "bigint": pa.int64(),
        "float": pa.float64(),
        "float32": pa.float32(),
        "float64": pa.float64(),
        "double": pa.float64(),
        "bool": pa.bool_(),
        "boolean": pa.bool_(),
        "date": pa.date32(),
        "timestamp": pa.timestamp("us"),
        "binary": pa.binary(),
    }
    if text in simple:
        return simple[text]
    raise ConnectorError(
        f"Tipo '{spec}' nao reconhecido em column_types. "
        f"Use decimal(p,s) ou um de: {', '.join(sorted(simple))}"
    )


def _number_to_arrow(precision: int | None, scale: int | None) -> pa.DataType:
    """Traduz NUMBER(p,s) do Oracle para o tipo Arrow mais fiel possivel."""
    # NUMBER sem precisao declarada: Oracle reporta precision=0 e scale=-127.
    if not precision or scale is None or scale == -127:
        return pa.float64()
    if scale == 0:
        return pa.int64() if precision <= 18 else pa.decimal128(min(precision, _MAX_PRECISION), 0)
    if scale < 0:  # NUMBER(p,-2): arredondado para dezenas/centenas
        return pa.decimal128(min(precision + abs(scale), _MAX_PRECISION), 0)
    return pa.decimal128(min(precision, _MAX_PRECISION), scale)


def _arrow_type_for(oracledb: Any, descriptor: Sequence[Any]) -> pa.DataType:
    name, type_code, _display, _internal, precision, scale, _null_ok = descriptor[:7]
    db = oracledb

    if type_code is db.DB_TYPE_NUMBER:
        return _number_to_arrow(precision, scale)
    if type_code in (db.DB_TYPE_BINARY_DOUBLE,):
        return pa.float64()
    if type_code in (db.DB_TYPE_BINARY_FLOAT,):
        return pa.float32()
    if type_code in (db.DB_TYPE_BINARY_INTEGER,):
        return pa.int64()
    if type_code in (db.DB_TYPE_DATE, db.DB_TYPE_TIMESTAMP):
        return pa.timestamp("us")
    if type_code in (db.DB_TYPE_TIMESTAMP_TZ, db.DB_TYPE_TIMESTAMP_LTZ):
        return pa.timestamp("us", tz="UTC")
    if type_code in (db.DB_TYPE_RAW, db.DB_TYPE_LONG_RAW, db.DB_TYPE_BLOB):
        return pa.binary()
    if type_code is getattr(db, "DB_TYPE_BOOLEAN", None):
        return pa.bool_()
    # VARCHAR2, CHAR, NVARCHAR2, CLOB, NCLOB, LONG, ROWID, XMLTYPE, JSON, INTERVAL...
    return pa.string()


def _coerce(values: list[Any], target: pa.DataType, column: str) -> pa.Array:
    """Converte uma coluna Python para o tipo Arrow alvo, tolerando nulos."""
    try:
        if pa.types.is_integer(target):
            values = [None if v is None else int(v) for v in values]
        elif pa.types.is_floating(target):
            values = [None if v is None else float(v) for v in values]
        elif pa.types.is_decimal(target):
            values = [None if v is None else _to_decimal(v, target) for v in values]
        elif pa.types.is_string(target):
            values = [None if v is None else _to_text(v) for v in values]
        elif pa.types.is_timestamp(target):
            values = [None if v is None else _to_datetime(v) for v in values]
        elif pa.types.is_date(target):
            values = [
                None if v is None else (v.date() if isinstance(v, dt.datetime) else v)
                for v in values
            ]
        return pa.array(values, type=target)
    except (ValueError, TypeError, InvalidOperation, pa.ArrowInvalid) as exc:
        raise ConnectorError(
            f"Falha ao converter a coluna '{column}' para {target}: {exc}. "
            f"Ajuste 'column_types' na configuracao da tabela."
        ) from exc


def _to_decimal(value: Any, target: pa.DataType) -> Decimal:
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    # Arrow rejeita valores com mais casas que o tipo declarado.
    return number.quantize(Decimal(1).scaleb(-target.scale))


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def _to_datetime(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    raise TypeError(f"valor {value!r} nao e data/hora")


@register_connector
class OracleConnector(Connector):
    """Le tabelas Oracle em lotes Arrow."""

    type_name = "oracle"

    def __init__(self, source: Any, settings: Any) -> None:
        super().__init__(source, settings)
        self._con: Any = None
        self._oracledb: Any = None

    # ------------------------------------------------------------------ conexao
    def _module(self) -> Any:
        if self._oracledb is None:
            try:
                import oracledb
            except ImportError as exc:  # pragma: no cover
                raise ConnectorError(
                    "Pacote 'oracledb' nao instalado. Rode: pip install oracledb"
                ) from exc
            self._oracledb = oracledb
        return self._oracledb

    def open(self) -> None:
        if self._con is not None:
            return
        oracledb = self._module()
        conn = self.source.connection

        dsn = require_resolved(conn.get("dsn"), f"{self.source.name}.connection.dsn")
        user = require_resolved(conn.get("user"), f"{self.source.name}.connection.user")
        password = require_resolved(
            conn.get("password"), f"{self.source.name}.connection.password"
        )

        if conn.get("thick_mode"):
            lib_dir = conn.get("lib_dir") or None
            if lib_dir and "${" in str(lib_dir):
                lib_dir = None
            try:
                oracledb.init_oracle_client(lib_dir=lib_dir)
            except Exception as exc:  # noqa: BLE001 - ja inicializado nao e erro
                if "DPI-1072" not in str(exc) and "already initialized" not in str(exc).lower():
                    raise ConnectorError(f"Falha ao iniciar o Oracle Client: {exc}") from exc

        timeout = int(conn.get("tcp_connect_timeout") or 15)
        try:
            self._con = oracledb.connect(
                user=user, password=password, dsn=dsn, tcp_connect_timeout=timeout
            )
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(
                f"Nao foi possivel conectar em '{self.source.name}' ({dsn}): {exc}"
                + _connection_hint(str(exc), dsn, timeout)
            ) from exc
        log.info("Conectado em %s (%s)", self.source.name, dsn)

    def close(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:  # noqa: BLE001 - fechar nunca deve derrubar a carga
                pass
            self._con = None

    def describe(self) -> str:
        self.open()
        with self._con.cursor() as cur:
            cur.execute(
                "SELECT user, SYS_CONTEXT('USERENV','DB_NAME'), "
                "SYS_CONTEXT('USERENV','SERVER_HOST') FROM dual"
            )
            user, db_name, host = cur.fetchone()
        mode = "thick" if self.source.connection.get("thick_mode") else "thin"
        return (
            f"Oracle {self._con.version} | banco={db_name} | host={host} "
            f"| usuario={user} | modo={mode}"
        )

    # -------------------------------------------------------------------- SQL
    def _column_list(self, table: TableConfig) -> str:
        if not table.columns:
            return "*"
        return ", ".join(_check_identifier(c, "Nome de coluna") for c in table.columns)

    def _from_clause(self, table: TableConfig) -> str:
        name = _check_identifier(table.name, "Nome de tabela")
        if table.schema:
            return f"{_check_identifier(table.schema, 'Schema')}.{name}"
        return name

    def _where_clause(self, table: TableConfig, since: Any) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        binds: dict[str, Any] = {}
        if since is not None and table.watermark_column:
            column = _check_identifier(table.watermark_column, "watermark_column")
            clauses.append(f"{column} > :wm")
            binds["wm"] = since
        if table.filter:
            clauses.append(f"({table.filter})")
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", binds

    def _build_query(self, table: TableConfig, since: Any) -> tuple[str, dict[str, Any]]:
        where, binds = self._where_clause(table, since)
        sql = f"SELECT {self._column_list(table)} FROM {self._from_clause(table)}{where}"
        return sql, binds

    # --------------------------------------------------------------- extracao
    def count(self, table: TableConfig, since: Any = None) -> int | None:
        self.open()
        where, binds = self._where_clause(table, since)
        sql = f"SELECT COUNT(*) FROM {self._from_clause(table)}{where}"
        with self._con.cursor() as cur:
            cur.execute(sql, binds)
            return int(cur.fetchone()[0])

    def extract(self, table: TableConfig, since: Any = None) -> Iterator[pa.Table]:
        self.open()
        oracledb = self._module()
        sql, binds = self._build_query(table, since)
        batch_rows = table.batch_rows or self.settings.batch_rows
        arraysize = min(self.settings.arraysize, batch_rows)

        log.info("SQL: %s %s", sql, f"(bind wm={binds['wm']})" if binds else "")

        cur = self._con.cursor()
        try:
            cur.arraysize = arraysize
            cur.prefetchrows = arraysize + 1
            cur.outputtypehandler = _lob_as_value(oracledb)
            cur.execute(sql, binds)

            overrides = {k.upper(): _parse_type_override(v) for k, v in table.column_types.items()}
            names = [d[0] for d in cur.description]
            unknown = set(overrides) - {n.upper() for n in names}
            if unknown:
                raise ConnectorError(
                    f"column_types referencia coluna(s) inexistente(s) em "
                    f"{table.qualified_name}: {', '.join(sorted(unknown))}"
                )
            types = [
                overrides.get(d[0].upper()) or _arrow_type_for(oracledb, d)
                for d in cur.description
            ]
            schema = pa.schema([pa.field(n, t) for n, t in zip(names, types)])

            pending: list[tuple[Any, ...]] = []
            yielded = False
            while True:
                rows = cur.fetchmany(arraysize)
                if not rows:
                    break
                pending.extend(rows)
                if len(pending) >= batch_rows:
                    yield _rows_to_arrow(pending, schema)
                    pending = []
                    yielded = True
            if pending:
                yield _rows_to_arrow(pending, schema)
            elif not yielded:
                # Nenhuma linha nova: devolve uma tabela vazia com o schema
                # correto para a bronze saber que a extracao rodou e nao falhou.
                yield schema.empty_table()
        finally:
            cur.close()


def _rows_to_arrow(rows: list[tuple[Any, ...]], schema: pa.Schema) -> pa.Table:
    columns = list(zip(*rows)) if rows else [() for _ in schema]
    arrays = [
        _coerce(list(values), field.type, field.name)
        for values, field in zip(columns, schema)
    ]
    return pa.Table.from_arrays(arrays, schema=schema)


def _lob_as_value(oracledb: Any):
    """Traz CLOB/BLOB como str/bytes direto, sem localizador de LOB.

    Ler LOB por localizador custa um round-trip por linha; nas tabelas de
    observacao de um ERP isso sozinho multiplica o tempo da carga.
    """

    def handler(cursor: Any, metadata: Any):
        code = metadata.type_code
        if code in (oracledb.DB_TYPE_CLOB, oracledb.DB_TYPE_NCLOB):
            return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)
        if code is oracledb.DB_TYPE_BLOB:
            return cursor.var(oracledb.DB_TYPE_LONG_RAW, arraysize=cursor.arraysize)
        if code is oracledb.DB_TYPE_NUMBER:
            # Decimal preserva centavos; float64 arredonda em valores longos.
            return cursor.var(
                oracledb.DB_TYPE_NUMBER, arraysize=cursor.arraysize, outconverter=_safe_decimal
            )
        return None

    return handler


def _connection_hint(error: str, dsn: str, timeout: int) -> str:
    """Traduz os erros de conexao mais comuns em uma proxima acao concreta."""
    host = dsn.split(":")[0]
    privado = host.startswith(("10.", "192.168.")) or host.startswith("172.")
    if "DPY-6005" in error or "timed out" in error.lower() or "refused" in error.lower():
        rede = (
            f"\n  O host {host} e um endereco de rede interna: so responde de dentro "
            f"dela (rede local, VPN ou uma maquina na mesma VCN)."
            if privado
            else ""
        )
        return (
            f"\n\nA conexao TCP nao chegou ao banco em {timeout}s -- isso acontece antes "
            f"de qualquer validacao de usuario e senha.{rede}"
            f"\n  Verifique nesta ordem:"
            f"\n    1. rota ate o host:  ping {host}"
            f"\n    2. porta aberta:     telnet {host} 1521  (ou Test-NetConnection no Windows)"
            f"\n    3. listener no ar:   lsnrctl status  (no servidor)"
        )
    if "ORA-01017" in error:
        return "\n\nUsuario ou senha invalidos. Cuidado com senha que precisa de aspas no .env."
    if "ORA-12514" in error:
        return (
            "\n\nO listener respondeu mas nao conhece esse service_name. Confira o nome "
            "com 'lsnrctl services' no servidor -- e service_name, nao SID."
        )
    if "ORA-28000" in error or "ORA-28001" in error:
        return "\n\nConta bloqueada ou senha expirada. Fale com o DBA."
    return ""


def _safe_decimal(value: Any) -> Any:
    if value is None or isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return value
