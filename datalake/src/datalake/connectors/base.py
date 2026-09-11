"""Contrato que todo conector de origem precisa cumprir."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator

import pyarrow as pa

from ..config import Settings, SourceConfig, TableConfig


class ConnectorError(Exception):
    """Falha ao conectar ou extrair dados da origem."""


class Connector(ABC):
    """Extrai lotes Arrow de um sistema de origem.

    A implementacao cuida apenas de *ler*: filtro incremental, paginacao e
    tipagem. Watermark, auditoria e escrita sao responsabilidade da camada bronze.
    """

    #: identificador usado no campo ``type`` do YAML da fonte
    type_name: str = ""

    def __init__(self, source: SourceConfig, settings: Settings) -> None:
        self.source = source
        self.settings = settings

    def __enter__(self) -> "Connector":
        self.open()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    @abstractmethod
    def open(self) -> None:
        """Abre a conexao com a origem."""

    @abstractmethod
    def close(self) -> None:
        """Fecha a conexao, sem levantar excecao se ja estiver fechada."""

    @abstractmethod
    def describe(self) -> str:
        """Uma linha legivel identificando servidor/usuario/versao."""

    @abstractmethod
    def extract(self, table: TableConfig, since: Any = None) -> Iterator[pa.Table]:
        """Gera lotes Arrow da tabela.

        ``since`` e o watermark ja tipado (ou ``None`` para carga total). Todos os
        lotes gerados precisam compartilhar exatamente o mesmo schema Arrow.
        """

    def count(self, table: TableConfig, since: Any = None) -> int | None:
        """Total estimado de linhas a extrair, ou ``None`` se nao souber."""
        return None
