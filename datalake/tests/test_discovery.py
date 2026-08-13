"""Sugestoes da introspeccao e validade do YAML gerado."""

from __future__ import annotations

import yaml

from datalake.config import SourceConfig
from datalake.discovery import ColumnInfo, TableInfo, to_yaml


def _col(nome, tipo="VARCHAR2", nullable=True):
    return ColumnInfo(name=nome, data_type=tipo, precision=None, scale=None, nullable=nullable)


def _tabela(nome="PEDIDOS", linhas=1_000_000, pk=("ID_PEDIDO",), colunas=None):
    return TableInfo(
        name=nome,
        num_rows=linhas,
        primary_key=list(pk),
        columns=colunas
        or [
            _col("ID_PEDIDO", "NUMBER", nullable=False),
            _col("DT_PEDIDO", "DATE"),
            _col("DT_ATUALIZACAO", "TIMESTAMP(6)"),
        ],
    )


# ------------------------------------------------------------------ sugestoes
def test_watermark_preferido_vence_outra_coluna_de_data():
    tabela = _tabela()
    assert tabela.suggested_watermark == "DT_ATUALIZACAO"
    assert tabela.watermark_candidates == ["DT_ATUALIZACAO", "DT_PEDIDO"]


def test_tabela_grande_com_pk_e_watermark_vira_incremental():
    assert _tabela(linhas=1_000_000).suggested_load_mode == "incremental"


def test_tabela_pequena_fica_full_mesmo_com_watermark():
    # Recarregar 5 mil linhas custa menos que manter estado incremental.
    assert _tabela(linhas=5_000).suggested_load_mode == "full"


def test_tabela_sem_coluna_de_data_fica_full():
    tabela = _tabela(colunas=[_col("ID_PEDIDO", "NUMBER", nullable=False), _col("NOME")])
    assert tabela.suggested_watermark is None
    assert tabela.suggested_load_mode == "full"
    assert "so carga full" in tabela.observacao


def test_tabela_sem_pk_fica_full_e_avisa():
    tabela = _tabela(pk=())
    assert tabela.suggested_load_mode == "full"
    assert "sem PK" in tabela.observacao


def test_volume_desconhecido_nao_impede_incremental():
    # num_rows vem NULL quando as estatisticas nunca foram coletadas.
    assert _tabela(linhas=None).suggested_load_mode == "incremental"


def test_data_sem_nome_conhecido_ainda_e_candidata():
    tabela = _tabela(
        colunas=[_col("ID_PEDIDO", "NUMBER", nullable=False), _col("DT_QUALQUER", "DATE")]
    )
    assert tabela.suggested_watermark == "DT_QUALQUER"


# ---------------------------------------------------------------------- YAML
def test_yaml_gerado_e_configuracao_valida():
    tabelas = [
        _tabela(),
        _tabela(nome="CLIENTES", linhas=800, pk=("ID_CLIENTE",)),
        _tabela(nome="LOG", linhas=50, pk=()),
    ]
    texto = to_yaml("oracle_erp", "ERP", tabelas)
    dados = yaml.safe_load(texto)

    source = SourceConfig.from_dict(dados)  # valida todas as regras de config
    assert source.name == "oracle_erp"
    assert source.type == "oracle"
    assert {t.name for t in source.tables} == {"PEDIDOS", "CLIENTES", "LOG"}

    pedidos = source.table("pedidos")
    assert pedidos.load_mode == "incremental"
    assert pedidos.watermark_column == "DT_ATUALIZACAO"
    assert pedidos.schema == "ERP"          # herdado de defaults
    assert pedidos.primary_key == ("ID_PEDIDO",)

    assert source.table("clientes").load_mode == "full"


def test_yaml_usa_snake_case_nos_testes_de_qualidade():
    """quality roda sobre a silver, onde os nomes ja foram normalizados."""
    dados = yaml.safe_load(to_yaml("erp", "ERP", [_tabela()]))
    quality = dados["tables"][0]["quality"]
    assert quality["unique"] == ["id_pedido"]
    assert "id_pedido" in quality["not_null"]


def test_yaml_referencia_variaveis_de_ambiente_e_nao_credenciais():
    texto = to_yaml("oracle_erp", "ERP", [_tabela()])
    assert "${ORACLE_ERP_DSN}" in texto
    assert "${ORACLE_ERP_PASSWORD}" in texto


def test_tabela_sem_pk_sai_comentada_para_preenchimento():
    dados = yaml.safe_load(to_yaml("erp", "ERP", [_tabela(nome="LOG", pk=())]))
    tabela = dados["tables"][0]
    assert "primary_key" not in tabela
    assert tabela["load_mode"] == "full"


# ------------------------------------------------------- recorte por volume
def test_top_pega_as_maiores_em_ordem():
    from datalake.discovery import select_tables

    tabelas = [_tabela(nome=n, linhas=r) for n, r in
               [("A", 10), ("B", 5_000_000), ("C", 300), ("D", 90_000)]]
    assert [t.name for t in select_tables(tabelas, top=2)] == ["B", "D"]


def test_min_rows_descarta_as_pequenas():
    from datalake.discovery import select_tables

    tabelas = [_tabela(nome=n, linhas=r) for n, r in [("A", 10), ("B", 5000), ("C", 999)]]
    assert [t.name for t in select_tables(tabelas, min_rows=1000)] == ["B"]


def test_tabela_sem_estatistica_vai_para_o_fim():
    """num_rows nulo significa 'estatistica nunca coletada', nao 'tabela vazia'."""
    from datalake.discovery import select_tables

    tabelas = [_tabela(nome="SEM_STATS", linhas=None), _tabela(nome="GRANDE", linhas=100)]
    assert [t.name for t in select_tables(tabelas, top=2)] == ["GRANDE", "SEM_STATS"]


def test_sem_recorte_devolve_tudo():
    from datalake.discovery import select_tables

    tabelas = [_tabela(nome="A", linhas=1), _tabela(nome="B", linhas=2)]
    assert len(select_tables(tabelas)) == 2


def test_lote_respeita_o_limite_da_clausula_in():
    from datalake.discovery import _chunks

    lotes = _chunks([f"T{i}" for i in range(1201)])
    assert [len(l) for l in lotes] == [500, 500, 201]
    assert all(len(l) <= 1000 for l in lotes)  # limite do Oracle


# ------------------------------------------------------------ varios filtros
def test_normalize_filters_aceita_str_lista_e_vazio():
    from datalake.discovery import normalize_filters

    assert normalize_filters("vei%") == ["VEI%"]
    assert normalize_filters(["vei%", " fat% "]) == ["VEI%", "FAT%"]
    assert normalize_filters(None) == ["%"]
    assert normalize_filters([]) == ["%"]
    assert normalize_filters(["", "  "]) == ["%"]


def test_clausula_like_combina_com_or():
    from datalake.discovery import _like_clause

    clausula, binds = _like_clause(["VEI%", "FAT%", "FIN%"])
    assert clausula == "(table_name LIKE :p0 OR table_name LIKE :p1 OR table_name LIKE :p2)"
    assert binds == {"p0": "VEI%", "p1": "FAT%", "p2": "FIN%"}


def test_clausula_like_com_um_padrao_so():
    from datalake.discovery import _like_clause

    clausula, binds = _like_clause(["%"])
    assert clausula == "(table_name LIKE :p0)"
    assert binds == {"p0": "%"}
