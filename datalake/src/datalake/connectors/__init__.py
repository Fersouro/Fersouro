"""Conectores de origem."""

from .base import Connector, ConnectorError
from .registry import get_connector, register_connector

__all__ = ["Connector", "ConnectorError", "get_connector", "register_connector"]
