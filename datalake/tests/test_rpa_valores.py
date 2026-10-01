from decimal import Decimal

import pytest

from datalake.rpa.valores import ValorInvalido, chave_numerica, formatar_brl, parse_brl


@pytest.mark.parametrize("texto,esperado", [
    ("R$ 1.234,56", "1234.56"),
    ("1.234,56", "1234.56"),
    ("1234,56", "1234.56"),
    ("R$1.234,5", "1234.50"),
    ("  R$ 1.234,56 ", "1234.56"),
    ("-1.234,56", "-1234.56"),
    ("R$ -1.234,56", "-1234.56"),
    ("-R$ 1.234,56", "-1234.56"),
    ("(1.234,56)", "-1234.56"),
    ("1.234,56-", "-1234.56"),
    ("1.234,56 D", "-1234.56"),
    ("1.234,56 C", "1234.56"),
    ("1.234.567,89", "1234567.89"),
    ("0,99", "0.99"),
    ("1234.56", "1234.56"),
    ("1.234", "1234.00"),
    ("1.234.567", "1234567.00"),
    ("15", "15.00"),
])
def test_parse_brl(texto, esperado):
    assert parse_brl(texto) == Decimal(esperado)


def test_parse_brl_numero_direto():
    assert parse_brl(1234.5) == Decimal("1234.50")
    assert parse_brl(Decimal("10")) == Decimal("10.00")


@pytest.mark.parametrize("texto", ["", "R$", "abc", "1,2,3", "12.34.5", "1.23,45", "1,234"])
def test_parse_brl_rejeita_ambiguo(texto):
    with pytest.raises(ValorInvalido):
        parse_brl(texto)


def test_formatar_brl():
    assert formatar_brl(Decimal("1245.8")) == "R$ 1.245,80"
    assert formatar_brl(Decimal("-3")) == "-R$ 3,00"


@pytest.mark.parametrize("valor,esperado", [
    (123456, "123456"), ("123456", "123456"), ("000123456", "123456"),
    (" 123.456 ", "123456"), (123456.0, "123456"), (None, ""), ("AB12", "ab12"),
    ("212.646A", "212646A"), ("212646a", "212646A"), ("211.827A", "211827A"),
])
def test_chave_numerica(valor, esperado):
    assert chave_numerica(valor) == esperado
def test_mojibake():
    from datalake.rpa.valores import normalizar_texto
    assert normalizar_texto("MÃªs") == "mes" and normalizar_texto("Mês") == "mes"


def test_os_com_A_e_outra_identificacao():
    """Regra de negocio: 123456A e relancamento, nao a mesma chave de 123456."""
    assert chave_numerica("212646A") != chave_numerica(212646)
    assert chave_numerica("212.646A") == chave_numerica("212646A")
