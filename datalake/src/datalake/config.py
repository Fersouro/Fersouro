"""Leitura e validacao das configuracoes (settings.yml + conf/sources/*.yml)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:  # opcional: carrega .env se python-dotenv estiver instalado
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# ${VAR} ou ${VAR:-valor padrao}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

VALID_LOAD_MODES = ("full", "incremental")
VALID_WATERMARK_TYPES = ("timestamp", "date", "number", "string")


class ConfigError(Exception):
    """Configuracao ausente ou invalida."""


def _expand(value: Any) -> Any:
    """Expande ${VAR} recursivamente em strings, listas e dicionarios.

    Variaveis sem valor e sem padrao sao mantidas como estao (``${VAR}``): assim
    comandos que nao tocam naquela fonte continuam funcionando, e quem for usar o
    valor chama :func:`require_resolved` para falhar com mensagem clara.
    """
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            var, default = match.group(1), match.group(2)
            resolved = os.environ.get(var, default)
            return match.group(0) if resolved is None else resolved

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def require_resolved(value: Any, what: str) -> str:
    """Garante que um valor de configuracao nao ficou com ${VAR} pendente."""
    if value is None or value == "":
        raise ConfigError(f"Configuracao obrigatoria ausente: {what}")
    text = str(value)
    pending = _ENV_PATTERN.findall(text)
    if pending:
        names = ", ".join(name for name, _ in pending)
        raise ConfigError(
            f"Configuracao '{what}' depende da(s) variavel(is) de ambiente {names}, "
            f"que nao esta(o) definida(s). Preencha o arquivo .env (veja .env.example)."
        )
    return text


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Arquivo de configuracao nao encontrado: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Esperado um mapeamento YAML em {path}")
    return _expand(data)


@dataclass(frozen=True)
class TableConfig:
    """Uma tabela de origem e como ela deve ser carregada."""

    name: str
    schema: str | None = None
    load_mode: str = "full"
    primary_key: tuple[str, ...] = ()
    watermark_column: str | None = None
    watermark_type: str = "timestamp"
    lookback: float = 0.0
    columns: tuple[str, ...] = ()
    exclude_columns: tuple[str, ...] = ()
    filter: str | None = None
    batch_rows: int = 200_000
    column_types: dict[str, str] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    @property
    def key(self) -> str:
        """Nome usado em diretorios e no banco de controle (sempre minusculo)."""
        return self.name.lower()

    def validate(self, source_name: str) -> None:
        where = f"{source_name}.{self.name}"
        if self.load_mode not in VALID_LOAD_MODES:
            raise ConfigError(
                f"[{where}] load_mode '{self.load_mode}' invalido; use um de {VALID_LOAD_MODES}"
            )
        if self.load_mode == "incremental" and not self.watermark_column:
            raise ConfigError(
                f"[{where}] load_mode 'incremental' exige 'watermark_column'"
            )
        if self.watermark_type not in VALID_WATERMARK_TYPES:
            raise ConfigError(
                f"[{where}] watermark_type '{self.watermark_type}' invalido; "
                f"use um de {VALID_WATERMARK_TYPES}"
            )
        if self.load_mode == "incremental" and not self.primary_key:
            raise ConfigError(
                f"[{where}] carga incremental exige 'primary_key' para deduplicar na silver"
            )
        if self.columns and self.watermark_column:
            upper = {c.upper() for c in self.columns}
            if self.watermark_column.upper() not in upper:
                raise ConfigError(
                    f"[{where}] 'watermark_column' precisa estar na lista 'columns'"
                )
        if self.columns and self.exclude_columns:
            raise ConfigError(
                f"[{where}] use 'columns' (lista branca) ou 'exclude_columns' "
                f"(lista negra), nao os dois"
            )
        if self.exclude_columns and self.watermark_column:
            excluidas = {c.upper() for c in self.exclude_columns}
            if self.watermark_column.upper() in excluidas:
                raise ConfigError(
                    f"[{where}] 'watermark_column' nao pode estar em 'exclude_columns'"
                )
        if self.batch_rows <= 0:
            raise ConfigError(f"[{where}] batch_rows deve ser > 0")


@dataclass(frozen=True)
class SourceConfig:
    """Um sistema de origem (um arquivo em conf/sources/)."""

    name: str
    type: str
    connection: dict[str, Any]
    tables: tuple[TableConfig, ...]
    path: Path | None = None

    def table(self, name: str) -> TableConfig:
        wanted = name.lower()
        for table in self.tables:
            if table.key == wanted:
                return table
        if not self.tables:
            raise ConfigError(
                f"A fonte '{self.name}' ainda nao tem tabelas configuradas. "
                f"Rode: datalake discover -s {self.name} --schema <SCHEMA> "
                f"--write conf/sources/{self.name}.yml --force"
            )
        available = ", ".join(t.name for t in self.tables)
        raise ConfigError(
            f"Tabela '{name}' nao existe na fonte '{self.name}'. Disponiveis: {available}"
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> "SourceConfig":
        name = data.get("name") or (path.stem if path else None)
        if not name:
            raise ConfigError(f"Fonte sem 'name' em {path}")
        source_type = data.get("type")
        if not source_type:
            raise ConfigError(f"Fonte '{name}' sem 'type' (ex.: oracle, duckdb)")

        defaults = data.get("defaults") or {}
        # Uma fonte sem tabelas e valida: e o estado inicial de quem ainda vai
        # rodar 'discover' para descobrir o que existe no schema. Ela responde a
        # test-connection e discover, e e ignorada pelo ingest.
        raw_tables = data.get("tables") or []

        tables: list[TableConfig] = []
        for raw in raw_tables:
            if isinstance(raw, str):  # forma curta: apenas o nome
                raw = {"name": raw}
            merged = {**defaults, **raw}
            table = TableConfig(
                name=merged["name"],
                schema=merged.get("schema"),
                load_mode=merged.get("load_mode", "full"),
                primary_key=tuple(merged.get("primary_key") or ()),
                watermark_column=merged.get("watermark_column"),
                watermark_type=merged.get("watermark_type", "timestamp"),
                lookback=float(merged.get("lookback") or 0),
                columns=tuple(merged.get("columns") or ()),
                exclude_columns=tuple(merged.get("exclude_columns") or ()),
                filter=merged.get("filter"),
                batch_rows=int(merged.get("batch_rows") or 200_000),
                column_types=dict(merged.get("column_types") or {}),
                quality=dict(merged.get("quality") or {}),
            )
            table.validate(name)
            tables.append(table)

        seen: set[str] = set()
        for table in tables:
            if table.key in seen:
                raise ConfigError(f"Fonte '{name}' tem a tabela '{table.name}' duplicada")
            seen.add(table.key)

        return cls(
            name=name,
            type=source_type,
            connection=dict(data.get("connection") or {}),
            tables=tuple(tables),
            path=path,
        )


@dataclass(frozen=True)
class Settings:
    """Configuracao global resolvida."""

    project_root: Path
    root: Path
    control_db: Path
    catalog_db: Path
    batch_rows: int
    arraysize: int
    compression: str
    duckdb_memory_limit: str
    duckdb_threads: int
    log_level: str
    log_dir: Path
    export_enabled: bool
    export_format: str
    export_dir: Path
    sources: tuple[SourceConfig, ...]

    # ---- caminhos das camadas ----
    @property
    def bronze(self) -> Path:
        return self.root / "bronze"

    @property
    def silver(self) -> Path:
        return self.root / "silver"

    @property
    def gold(self) -> Path:
        return self.root / "gold"

    @property
    def sql_dir(self) -> Path:
        return self.project_root / "sql"

    def source(self, name: str) -> SourceConfig:
        wanted = name.lower()
        for source in self.sources:
            if source.name.lower() == wanted:
                return source
        available = ", ".join(s.name for s in self.sources) or "(nenhuma)"
        raise ConfigError(f"Fonte '{name}' nao encontrada. Disponiveis: {available}")


def load_settings(project_root: Path | str | None = None) -> Settings:
    """Carrega settings.yml e todas as fontes de conf/sources/."""
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    root = root.resolve()

    if load_dotenv is not None:
        env_file = root / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)

    data = _load_yaml(root / "conf" / "settings.yml")
    lake = data.get("lake") or {}
    runtime = data.get("runtime") or {}
    logging_cfg = data.get("logging") or {}
    export_cfg = data.get("export") or {}

    def _path(value: str | None, default: str) -> Path:
        candidate = Path(value or default)
        return candidate if candidate.is_absolute() else (root / candidate).resolve()

    lake_root = _path(lake.get("root"), "./data")

    sources: list[SourceConfig] = []
    sources_dir = root / "conf" / "sources"
    if sources_dir.is_dir():
        for path in sorted(sources_dir.glob("*.y*ml")):
            sources.append(SourceConfig.from_dict(_load_yaml(path), path))

    return Settings(
        project_root=root,
        root=lake_root,
        control_db=_path(lake.get("control_db"), "./data/_control/control.duckdb"),
        catalog_db=_path(lake.get("catalog_db"), "./data/lake.duckdb"),
        batch_rows=int(runtime.get("batch_rows") or 200_000),
        arraysize=int(runtime.get("arraysize") or 10_000),
        compression=str(runtime.get("compression") or "zstd"),
        duckdb_memory_limit=str(runtime.get("duckdb_memory_limit") or "4GB"),
        duckdb_threads=int(runtime.get("duckdb_threads") or 4),
        export_enabled=bool(export_cfg.get("enabled", True)),
        export_format=str(export_cfg.get("format") or "xlsx").lower(),
        export_dir=_path(export_cfg.get("dir"), "./data/export"),
        log_level=str(logging_cfg.get("level") or "INFO").upper(),
        log_dir=_path(logging_cfg.get("dir"), "./logs"),
        sources=tuple(sources),
    )
