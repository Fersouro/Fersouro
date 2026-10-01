"""Fonte recem-criada, antes do discover: valida mas nao carrega nada.

Ordem real de uso: cria a fonte com a conexao -> roda discover -> so entao
existem tabelas. A configuracao precisa aceitar esse estado intermediario.
"""

from __future__ import annotations

import pytest
import yaml

from datalake.config import ConfigError, SourceConfig, load_settings
from datalake.layers import bronze, silver
from datalake.state.control import new_run_id

STUB = {
    "name": "ccm",
    "type": "oracle",
    "connection": {"dsn": "h:1521/x", "user": "u", "password": "p"},
    "defaults": {"schema": "CCM"},
    "tables": [],
}


def test_fonte_sem_tabelas_e_valida():
    source = SourceConfig.from_dict(STUB)
    assert source.tables == ()
    assert source.name == "ccm"


def test_chave_tables_ausente_equivale_a_lista_vazia():
    dados = {k: v for k, v in STUB.items() if k != "tables"}
    assert SourceConfig.from_dict(dados).tables == ()


def test_erro_de_tabela_orienta_a_rodar_discover():
    with pytest.raises(ConfigError, match="discover"):
        SourceConfig.from_dict(STUB).table("qualquer")


def test_carregada_junto_das_demais(project):
    (project / "conf" / "sources" / "ccm.yml").write_text(
        yaml.safe_dump(STUB), encoding="utf-8"
    )
    settings = load_settings(project)
    assert {s.name for s in settings.sources} == {"erp", "ccm"}
    assert settings.source("ccm").tables == ()


def test_ingest_ignora_a_fonte_sem_abrir_conexao(project, control):
    """Nao pode tentar conectar: a fonte stub aponta para um host inexistente."""
    (project / "conf" / "sources" / "ccm.yml").write_text(
        yaml.safe_dump(STUB), encoding="utf-8"
    )
    settings = load_settings(project)
    resultado = bronze.ingest_source(
        settings, settings.source("ccm"), control, new_run_id()
    )
    assert resultado == []


def test_silver_ignora_a_fonte_sem_tabelas(project, control):
    (project / "conf" / "sources" / "ccm.yml").write_text(
        yaml.safe_dump(STUB), encoding="utf-8"
    )
    settings = load_settings(project)
    assert silver.build_source(settings, settings.source("ccm"), control, new_run_id()) == []


def test_a_fonte_de_verdade_continua_carregando(settings):
    """A flexibilizacao nao pode deixar passar fonte mal configurada."""
    with pytest.raises(ConfigError, match="load_mode"):
        SourceConfig.from_dict({**STUB, "tables": [{"name": "T", "load_mode": "xpto"}]})
