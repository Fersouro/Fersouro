"""Configuracao: expansao de ambiente, heranca de defaults e validacoes."""

from __future__ import annotations

import pytest
import yaml

from datalake.config import ConfigError, SourceConfig, require_resolved


def _source(**overrides):
    data = {
        "name": "erp",
        "type": "oracle",
        "connection": {"dsn": "host:1521/orcl"},
        "defaults": {"schema": "ERP", "batch_rows": 5000},
        "tables": [{"name": "CLIENTES", "load_mode": "full", "primary_key": ["ID"]}],
    }
    data.update(overrides)
    return SourceConfig.from_dict(data)


def test_defaults_sao_herdados_pelas_tabelas():
    table = _source().tables[0]
    assert table.schema == "ERP"
    assert table.batch_rows == 5000
    assert table.qualified_name == "ERP.CLIENTES"
    assert table.key == "clientes"


def test_tabela_pode_sobrescrever_default():
    source = _source(
        tables=[{"name": "PEDIDOS", "schema": "OUTRO", "primary_key": ["ID"]}]
    )
    assert source.tables[0].schema == "OUTRO"


def test_tabela_em_forma_curta():
    source = _source(tables=["LOG_ACESSO"])
    assert source.tables[0].name == "LOG_ACESSO"
    assert source.tables[0].load_mode == "full"


def test_incremental_exige_watermark():
    with pytest.raises(ConfigError, match="watermark_column"):
        _source(tables=[{"name": "P", "load_mode": "incremental", "primary_key": ["ID"]}])


def test_incremental_exige_primary_key():
    with pytest.raises(ConfigError, match="primary_key"):
        _source(
            tables=[
                {"name": "P", "load_mode": "incremental", "watermark_column": "DT"}
            ]
        )


def test_load_mode_invalido():
    with pytest.raises(ConfigError, match="load_mode"):
        _source(tables=[{"name": "P", "load_mode": "delta"}])


def test_watermark_precisa_estar_na_projecao():
    with pytest.raises(ConfigError, match="columns"):
        _source(
            tables=[
                {
                    "name": "P",
                    "load_mode": "incremental",
                    "primary_key": ["ID"],
                    "watermark_column": "DT",
                    "columns": ["ID", "NOME"],
                }
            ]
        )


def test_tabela_duplicada():
    with pytest.raises(ConfigError, match="duplicada"):
        _source(tables=["X", "x"])


def test_fonte_sem_tabelas():
    with pytest.raises(ConfigError, match="nenhuma tabela"):
        _source(tables=[])


def test_busca_de_tabela_ignora_caixa():
    assert _source().table("clientes").name == "CLIENTES"
    with pytest.raises(ConfigError, match="nao existe"):
        _source().table("inexistente")


def test_expansao_de_variavel_de_ambiente(monkeypatch, project):
    monkeypatch.setenv("MINHA_VAR", "valor-teste")
    path = project / "conf" / "sources" / "outra.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "outra",
                "type": "duckdb",
                "connection": {"database": "${MINHA_VAR}", "extra": "${SEM_VALOR:-padrao}"},
                "tables": ["t"],
            }
        ),
        encoding="utf-8",
    )
    from datalake.config import load_settings

    settings = load_settings(project)
    conn = settings.source("outra").connection
    assert conn["database"] == "valor-teste"
    assert conn["extra"] == "padrao"


def test_variavel_ausente_falha_so_no_uso(project):
    """Sem valor, o placeholder sobrevive ate alguem exigir o valor resolvido."""
    path = project / "conf" / "sources" / "faltando.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "faltando",
                "type": "oracle",
                "connection": {"dsn": "${VAR_QUE_NAO_EXISTE}"},
                "tables": ["t"],
            }
        ),
        encoding="utf-8",
    )
    from datalake.config import load_settings

    settings = load_settings(project)  # nao levanta
    dsn = settings.source("faltando").connection["dsn"]
    assert dsn == "${VAR_QUE_NAO_EXISTE}"
    with pytest.raises(ConfigError, match="VAR_QUE_NAO_EXISTE"):
        require_resolved(dsn, "faltando.connection.dsn")


def test_caminhos_do_lake(settings):
    assert settings.bronze.name == "bronze"
    assert settings.silver.name == "silver"
    assert settings.gold.name == "gold"
    assert settings.control_db.parent.name == "_control"
    assert {s.name for s in settings.sources} == {"erp"}
