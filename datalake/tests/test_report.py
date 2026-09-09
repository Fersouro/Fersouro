"""Camada de relatorios: definicao em YAML -> pasta de trabalho .xlsx."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from datalake.config import ConfigError
from datalake.report import (
    FORMATS,
    ReportConfig,
    build_all,
    column_formats,
    infer_format,
    load_reports,
)

RELATORIO_YML = """
name: pedidos
title: Pedidos por cliente
description: Relatorio de teste.
formats:
  vlr_total: moeda
sheets:
  - name: Resumo
    description: Total por cliente.
    sql: |
      SELECT nome, sum(vlr_total) AS vlr_total, count(*) AS qtd_pedidos
        FROM pedidos_cliente
       GROUP BY nome
       ORDER BY nome
    totals: [vlr_total, qtd_pedidos]
    highlights:
      - when: vlr_total > 200
        style: amarelo
  - name: Detalhe
    model: pedidos_cliente
"""


@pytest.fixture
def lake_com_gold(project, settings, control):
    """Roda ingest -> silver -> gold para ter um modelo materializado."""
    from datalake.layers import bronze, gold, silver

    bronze.ingest_source(settings, settings.source("erp"), control, "t1")
    silver.build_source(settings, settings.source("erp"), control, "t1")
    gold.build_all(settings, control, "t1")
    return settings


def _escrever_relatorio(project, conteudo=RELATORIO_YML, nome="pedidos.yml"):
    pasta = project / "conf" / "reports"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_text(conteudo, encoding="utf-8")


# ------------------------------------------------------------------ formatos


def test_dinheiro_pelo_nome_da_coluna():
    """O tipo nao distingue: float chamado venda_total e dinheiro."""
    assert infer_format("venda_total", [Decimal("10.5")]) == FORMATS["moeda"]
    assert infer_format("preco_medio", [1.5]) == FORMATS["moeda"]


def test_revenda_e_numero_da_loja_nao_dinheiro():
    """'revenda' contem 'venda' -- nao pode virar R$."""
    assert infer_format("revenda", [1, 2]) == FORMATS["inteiro"]


def test_porcentagem_nao_multiplica_de_novo():
    """A gold ja entrega 12.5 para 12,5%; o formato '%' do Excel multiplicaria."""
    formato = infer_format("lucro_porcentagem", [12.5])
    assert formato == FORMATS["percentual"]
    assert "%" in formato and not formato.endswith("0.0%")


def test_data_e_competencia():
    assert infer_format("emissao", [dt.date(2026, 8, 13)]) == FORMATS["data"]
    assert infer_format("competencia", [dt.datetime(2026, 8, 1)]) == FORMATS["mes"]
    assert infer_format("dta_documento", [dt.datetime(2026, 8, 13, 9, 30)]) == FORMATS["data_hora"]


def test_texto_e_nulo_ficam_sem_formato():
    assert infer_format("descricao", ["parafuso"]) is None
    assert infer_format("qualquer", [None, None]) is None


def test_formato_declarado_vence_a_inferencia():
    formatos = column_formats(["valor"], [(Decimal("1"),)], {"valor": "inteiro"})
    assert formatos == [FORMATS["inteiro"]]


def test_mascara_crua_do_excel_passa_direto():
    assert column_formats(["x"], [(1.0,)], {"x": '#,##0.000'}) == ['#,##0.000']


# ----------------------------------------------------------------- definicao


def test_model_vira_select_estrela():
    cfg = ReportConfig.from_dict(
        {"name": "r", "sheets": [{"name": "A", "model": "margem_pecas"}]}
    )
    assert cfg.sheets[0].sql == 'SELECT * FROM "margem_pecas"'


def test_sql_e_model_juntos_e_erro():
    with pytest.raises(ConfigError, match="nao os dois"):
        ReportConfig.from_dict(
            {"name": "r", "sheets": [{"name": "A", "sql": "SELECT 1", "model": "x"}]}
        )


def test_aba_sem_origem_e_erro():
    with pytest.raises(ConfigError, match="falta 'sql' ou 'model'"):
        ReportConfig.from_dict({"name": "r", "sheets": [{"name": "A"}]})


def test_estilo_invalido_e_erro():
    with pytest.raises(ConfigError, match="estilo"):
        ReportConfig.from_dict(
            {
                "name": "r",
                "sheets": [
                    {"name": "A", "sql": "SELECT 1", "highlights": [{"when": "1=1", "style": "roxo"}]}
                ],
            }
        )


def test_relatorio_sem_abas_e_erro():
    with pytest.raises(ConfigError, match="sem 'sheets'"):
        ReportConfig.from_dict({"name": "r"})


def test_load_reports_le_a_pasta(project, settings):
    _escrever_relatorio(project)
    relatorios = load_reports(settings)
    assert [r.name for r in relatorios] == ["pedidos"]
    assert relatorios[0].title == "Pedidos por cliente"


def test_sem_pasta_de_relatorios_nao_falha(settings):
    assert load_reports(settings) == []
    assert build_all(settings) == []


def test_relatorio_inexistente(project, settings):
    _escrever_relatorio(project)
    with pytest.raises(ValueError, match="inexistente"):
        build_all(settings, apenas=["nao_existe"])


# -------------------------------------------------------------------- saida


def test_gera_xlsx_com_capa_totais_e_destaque(project, lake_com_gold, tmp_path):
    _escrever_relatorio(project)
    destino = tmp_path / "saida"
    resultados = build_all(lake_com_gold, destino_dir=destino)

    assert [r.status for r in resultados] == ["success"]
    caminho = resultados[0].path
    assert caminho == destino / "pedidos.xlsx"

    wb = load_workbook(caminho)
    # A capa vem primeiro: quem recebe a planilha sabe o que e e de quando.
    assert wb.sheetnames == ["Capa", "Resumo", "Detalhe"]
    assert wb["Capa"]["A1"].value == "Pedidos por cliente"

    ws = wb["Resumo"]
    assert [c.value for c in ws[1]] == ["nome", "vlr_total", "qtd_pedidos"]
    assert ws.freeze_panes == "A2"
    assert ws["B2"].number_format == FORMATS["moeda"]
    assert ws["C2"].number_format == FORMATS["inteiro"]

    # Uma linha de total, com SUBTOTAL para acompanhar o filtro.
    ultima = ws.max_row
    assert ws.cell(ultima, 1).value == "TOTAL"
    assert ws.cell(ultima, 2).value.startswith("=SUBTOTAL(109,")
    assert ws.auto_filter.ref.endswith(str(ultima - 1))   # o total fica fora do filtro


def test_destaque_pinta_a_linha_que_bate_na_condicao(project, lake_com_gold, tmp_path):
    _escrever_relatorio(project)
    wb = load_workbook(build_all(lake_com_gold, destino_dir=tmp_path)[0].path)
    ws = wb["Resumo"]

    pintadas = {
        ws.cell(linha, 1).value
        for linha in range(2, ws.max_row)
        if ws.cell(linha, 1).fill.fgColor.rgb == "00FFEB9C"
    }
    # 'Beta' tem pedido de 250,50 -- unico acima de 200.
    assert pintadas == {"Beta"}


def test_destaque_em_uma_coluna_so(project, lake_com_gold, tmp_path):
    _escrever_relatorio(
        project,
        """
name: escopo
sheets:
  - name: Resumo
    sql: SELECT nome, vlr_total FROM pedidos_cliente ORDER BY nome
    highlights:
      - when: vlr_total > 200
        style: vermelho
        scope: vlr_total
""",
        "escopo.yml",
    )
    resultado = [r for r in build_all(lake_com_gold, destino_dir=tmp_path) if r.report == "escopo"][0]
    ws = load_workbook(resultado.path)["Resumo"]
    linha = next(i for i in range(2, ws.max_row + 1) if ws.cell(i, 1).value == "Beta")
    assert ws.cell(linha, 2).fill.fgColor.rgb == "00FFC7CE"
    assert ws.cell(linha, 1).fill.fgColor.rgb != "00FFC7CE"     # so a coluna pedida


def test_modelo_ausente_e_skipped_nao_falha(project, settings, tmp_path):
    """Relatorio que cita modelo ainda nao carregado nao derruba a execucao."""
    _escrever_relatorio(
        project,
        "name: futuro\nsheets:\n  - name: A\n    model: nao_carregado\n",
        "futuro.yml",
    )
    resultados = build_all(settings, destino_dir=tmp_path)
    assert [r.status for r in resultados] == ["skipped"]
    assert all(r.ok for r in resultados)


def test_total_de_coluna_inexistente_falha_com_mensagem(project, lake_com_gold, tmp_path):
    _escrever_relatorio(
        project,
        "name: ruim\nsheets:\n  - name: A\n    model: pedidos_cliente\n    totals: [nao_existe]\n",
        "ruim.yml",
    )
    resultado = [r for r in build_all(lake_com_gold, destino_dir=tmp_path) if r.report == "ruim"][0]
    assert resultado.status == "failed"
    assert "nao_existe" in resultado.message


def test_corte_no_teto_do_excel_conta_o_que_ficou_de_fora(lake_com_gold):
    """A aba grava o que cabe e diz o total real -- sem carregar tudo."""
    from datalake.duck import connect
    from datalake.layers.gold import register_silver_views
    from datalake.report import SheetConfig, fetch_sheet, register_gold_views

    con = connect(lake_com_gold)
    register_silver_views(con, lake_com_gold)
    register_gold_views(con, lake_com_gold)
    try:
        sheet = SheetConfig(name="A", sql="SELECT * FROM pedidos_cliente")
        colunas, linhas, _, total = fetch_sheet(con, sheet, max_rows=1)
        assert len(linhas) == 1
        assert total == 2            # dois pedidos nao cancelados na base de teste
    finally:
        con.close()


def test_limit_declarado_nao_dispara_contagem(lake_com_gold):
    from datalake.duck import connect
    from datalake.layers.gold import register_silver_views
    from datalake.report import SheetConfig, fetch_sheet, register_gold_views

    con = connect(lake_com_gold)
    register_silver_views(con, lake_com_gold)
    register_gold_views(con, lake_com_gold)
    try:
        sheet = SheetConfig(name="A", sql="SELECT * FROM pedidos_cliente", limit=1)
        _, linhas, _, total = fetch_sheet(con, sheet, max_rows=1000)
        assert len(linhas) == 1 and total == 1     # limite pedido nao e aviso
    finally:
        con.close()
