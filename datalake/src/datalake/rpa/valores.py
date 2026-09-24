"""Conversao de textos do padrao brasileiro (dinheiro, numero, chave).

Tudo aqui e puro -- sem PDF, sem Excel -- para ser testado a parte.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_DIGITOS_E_SEPARADORES = re.compile(r"\d[\d.,\s]*")


class ValorInvalido(ValueError):
    """Texto que nao da para converter em numero com seguranca."""


def corrigir_mojibake(texto: str) -> str:
    """'MÃªs' -> 'Mês': UTF-8 lido como Latin-1 (comum em portal antigo sem charset)."""
    if "Ã" not in texto and "Â" not in texto:
        return texto
    try:
        return texto.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            return texto.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return texto


def normalizar_texto(texto: str) -> str:
    """Minusculo, sem acento, espacos simples -- para comparar rotulos e cabecalhos."""
    sem_acento = unicodedata.normalize("NFKD", corrigir_mojibake(str(texto or "")))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def parse_brl(texto: str | int | float | Decimal) -> Decimal:
    """Converte valor monetario brasileiro em Decimal (2 casas).

    Aceita: "R$ 1.234,56", "1.234,56", "1234,56", "-1.234,56", "R$ -1.234,56",
    "(1.234,56)", "1.234,56-", "1.234,56 D" (debito), "1234.56", "1.234" (mil),
    espacos e NBSP no meio. Numeros (int/float/Decimal) passam direto.

    Regra do separador: a virgula e sempre decimal. Sem virgula, um unico ponto
    seguido de exatamente 2 digitos no fim e decimal ("1234.56"); qualquer outro
    ponto e milhar ("1.234", "1.234.567").
    """
    if isinstance(texto, bool):
        raise ValorInvalido(f"valor booleano nao e dinheiro: {texto!r}")
    if isinstance(texto, (int, float, Decimal)):
        return Decimal(str(texto)).quantize(Decimal("0.01"))

    bruto = str(texto or "").replace(" ", " ").strip()
    if not bruto:
        raise ValorInvalido("valor vazio")

    negativo = False
    t = bruto.upper().replace("R$", " ").replace("RS ", " ").strip()
    if t.startswith("(") and t.endswith(")"):
        negativo, t = True, t[1:-1].strip()
    if t.endswith("-"):
        negativo, t = True, t[:-1].strip()
    if t.endswith(" D") or t.endswith(" DB"):
        negativo, t = True, t.rsplit(" ", 1)[0].strip()
    elif t.endswith(" C") or t.endswith(" CR"):
        t = t.rsplit(" ", 1)[0].strip()
    if t.startswith("-"):
        negativo, t = True, t[1:].strip()
    elif t.startswith("+"):
        t = t[1:].strip()
    if t.startswith("R$"):
        t = t[2:].strip()

    t = t.replace(" ", "")
    if not t or not re.fullmatch(r"[\d.,]+", t) or not re.search(r"\d", t):
        raise ValorInvalido(f"nao parece valor monetario: {bruto!r}")

    if "," in t:
        inteiro, _, decimal = t.rpartition(",")
        if "," in inteiro or not decimal.isdigit() or len(decimal) > 2:
            raise ValorInvalido(f"separadores inconsistentes: {bruto!r}")
        if inteiro and not re.fullmatch(r"\d{1,3}(\.\d{3})*|\d+", inteiro):
            raise ValorInvalido(f"milhar mal formado: {bruto!r}")
        normal = f"{inteiro.replace('.', '') or '0'}.{decimal}"
    elif t.count(".") == 1 and re.fullmatch(r"\d+\.\d{2}", t):
        normal = t
    else:
        if "." in t and not re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
            raise ValorInvalido(f"milhar mal formado: {bruto!r}")
        normal = t.replace(".", "")

    try:
        valor = Decimal(normal).quantize(Decimal("0.01"))
    except InvalidOperation as exc:  # pragma: no cover - regex acima ja filtra
        raise ValorInvalido(f"nao converti {bruto!r}") from exc
    return -valor if negativo else valor


def formatar_brl(valor: Decimal | float) -> str:
    """Decimal('1234.5') -> 'R$ 1.234,50' (so para log)."""
    v = Decimal(str(valor)).quantize(Decimal("0.01"))
    sinal = "-" if v < 0 else ""
    inteiro, _, dec = f"{abs(v):.2f}".partition(".")
    grupos = f"{int(inteiro):,}".replace(",", ".")
    return f"{sinal}R$ {grupos},{dec}"


def chave_numerica(valor) -> str:
    """Chave de comparacao para numeros de documento (SG, NF).

    123456, "123456", "000123456", " 123.456 ", 123456.0 -> "123456".
    Texto com letras fica como esta (normalizado), para nao casar errado.
    """
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    so_digitos = re.sub(r"[\s.\-/]", "", texto)
    if so_digitos.isdigit():
        return so_digitos.lstrip("0") or "0"
    return normalizar_texto(texto)
