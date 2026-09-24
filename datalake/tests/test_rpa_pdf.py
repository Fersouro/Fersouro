from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from datalake.rpa.pdf_extrator import (ErroExtracao, Layout, extrair_pdf, extrair_texto,
                                       validar_pdf)
from pdf_fake import gerar_pdf, pdf_sg

CONF = Path(__file__).resolve().parents[1] / "conf" / "rpa" / "saga_vh47.yml"


@pytest.fixture(scope="module")
def layouts():
    bruto = yaml.safe_load(CONF.read_text(encoding="utf-8"))
    return [Layout.from_dict(l) for l in bruto["extracao"]["layouts"]]


def test_uma_sg_por_pdf_ignora_numeros_isca(tmp_path, layouts):
    pdf = pdf_sg(tmp_path / "r.pdf", "123456", "R$ 1.245,80")
    r = extrair_pdf(pdf, layouts)
    assert r.registros == [{"sg": "123456", "valor_total": Decimal("1245.80")}]


def test_total_negativo_e_sem_rs(tmp_path, layouts):
    pdf = pdf_sg(tmp_path / "r.pdf", "000987654", "-2.000,00")
    r = extrair_pdf(pdf, layouts)
    assert r.registros == [{"sg": "987654", "valor_total": Decimal("-2000.00")}]


def test_layout_tabela_valor_na_linha_de_baixo(tmp_path, layouts):
    pdf = gerar_pdf(tmp_path / "t.pdf", [[
        (50, 800, "RELATORIO VH47"),
        (50, 760, "Nº SG"), (200, 760, "Data"), (350, 760, "Valor Total da SG"),
        (50, 745, "555001"), (200, 745, "01/09/2025"), (350, 745, "3.210,99"),
    ]])
    r = extrair_pdf(pdf, layouts)
    assert r.registros == [{"sg": "555001", "valor_total": Decimal("3210.99")}]


def test_varias_sgs_no_mesmo_pdf(tmp_path, layouts):
    pdf = gerar_pdf(tmp_path / "v.pdf", [
        [(50, 800, "SG Nº 111111"), (50, 780, "Valor Total da SG: 100,00"),
         (50, 740, "SG Nº 222222"), (50, 720, "Valor Total da SG: 2.000,50")],
        [(50, 800, "SG Nº 333333"), (50, 780, "Valor Total da SG: R$ 30,00")],
    ])
    r = extrair_pdf(pdf, layouts)
    assert [(x["sg"], x["valor_total"]) for x in r.registros] == [
        ("111111", Decimal("100.00")), ("222222", Decimal("2000.50")), ("333333", Decimal("30.00"))]


def test_cabecalho_repetido_por_pagina_nao_duplica(tmp_path, layouts):
    pag = [(50, 800, "Nº SG: 444444"), (50, 700, "Valor Total da SG: 10,00")]
    pdf = gerar_pdf(tmp_path / "p.pdf", [pag, pag])
    assert len(extrair_pdf(pdf, layouts).registros) == 1


def test_sem_sg_erro_claro(tmp_path, layouts):
    pdf = gerar_pdf(tmp_path / "x.pdf", [[(50, 800, "Valor Total da SG: 10,00")]])
    with pytest.raises(ErroExtracao, match="localizar o numero da SG"):
        extrair_pdf(pdf, layouts)


def test_sem_total_erro_claro(tmp_path, layouts):
    pdf = gerar_pdf(tmp_path / "x.pdf", [[(50, 800, "Nº SG: 777777"), (50, 780, "Peças: 10,00")]])
    with pytest.raises(ErroExtracao, match="Valor total nao identificado"):
        extrair_pdf(pdf, layouts)


def test_total_ambiguo_nao_chuta(tmp_path, layouts):
    pdf = gerar_pdf(tmp_path / "x.pdf", [[
        (50, 800, "Nº SG: 777777"), (50, 780, "Valor Total da SG: 10,00"),
        (50, 760, "Valor Total da SG: 99,00")]])
    with pytest.raises(ErroExtracao, match="ambiguo"):
        extrair_pdf(pdf, layouts)


def test_prioridade_do_rotulo(tmp_path, layouts):
    # "Valor Total" generico existe, mas o rotulo especifico da SG manda
    pdf = gerar_pdf(tmp_path / "x.pdf", [[
        (50, 800, "Nº SG: 777777"), (50, 780, "Valor Total: 5,00"),
        (50, 760, "Valor Total da SG: 12,34")]])
    assert extrair_pdf(pdf, layouts).registros[0]["valor_total"] == Decimal("12.34")


def test_layout_identificado_por_texto(tmp_path):
    layouts = [
        Layout.from_dict({"nome": "extrato", "identificar": "extrato de pagamento", "chave": "sg",
                          "campos": {"sg": {"tipo": "documento", "rotulos": ["solicitacao"]},
                                     "valor_total": {"tipo": "dinheiro", "rotulos": ["liquido"]}}}),
        Layout.from_dict({"nome": "padrao", "campos": {"sg": {"tipo": "documento", "rotulos": ["sg"]}}}),
    ]
    r = extrair_texto("EXTRATO DE PAGAMENTO\nSolicitação 998877\nLíquido 1.000,00", layouts)
    assert r.layout == "extrato"
    assert r.registros == [{"sg": "998877", "valor_total": Decimal("1000.00")}]


def test_validar_pdf_detecta_incompleto_e_html(tmp_path):
    bom = pdf_sg(tmp_path / "ok.pdf", "1", "1,00")
    assert validar_pdf(bom) == 1
    cortado = tmp_path / "cortado.pdf"
    cortado.write_bytes(bom.read_bytes()[: len(bom.read_bytes()) // 2])
    with pytest.raises(ErroExtracao, match="incompleto"):
        validar_pdf(cortado)
    html = tmp_path / "erro.pdf"
    html.write_text("<html>sessao expirada</html>")
    with pytest.raises(ErroExtracao, match="nao e um PDF"):
        validar_pdf(html)
    vazio = tmp_path / "vazio.pdf"
    vazio.write_bytes(b"")
    with pytest.raises(ErroExtracao):
        validar_pdf(vazio)


def test_sg_com_sufixo_A_preservada(tmp_path, layouts):
    pdf = pdf_sg(tmp_path / "a.pdf", "212646A", "R$ 10,00")
    assert extrair_pdf(pdf, layouts).registros[0]["sg"] == "212646A"
