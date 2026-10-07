"""Registro de conectores por nome de tipo."""

from __future__ import annotations

from typing import Type

from ..config import Settings, SourceConfig
from .base import Connector, ConnectorError

_REGISTRY: dict[str, Type[Connector]] = {}
_builtins_loaded = False


def register_connector(cls: Type[Connector]) -> Type[Connector]:
    """Decorador que registra a classe pelo seu ``type_name``."""
    if not cls.type_name:
        raise ValueError(f"{cls.__name__} precisa definir type_name")
    _REGISTRY[cls.type_name.lower()] = cls
    return cls


def available_types() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def get_connector(source: SourceConfig, settings: Settings) -> Connector:
    _load_builtin()
    cls = _REGISTRY.get(source.type.lower())
    if cls is None:
        raise ConnectorError(
            f"Fonte '{source.name}': tipo '{source.type}' desconhecido. "
            f"Tipos disponiveis: {', '.join(available_types())}"
        )
    return cls(source, settings)


def _load_builtin() -> None:
    """Importa os conectores nativos na primeira consulta (evita import circular).

    O controle e um flag proprio, e nao "o registro esta vazio": importar um
    modulo de conector direto ja o auto-registra, e o registro parcial faria os
    demais conectores nunca serem carregados.
    """
    global _builtins_loaded
    if _builtins_loaded:
        return
    from . import duckdb_source, oracle  # noqa: F401

    _builtins_loaded = True
