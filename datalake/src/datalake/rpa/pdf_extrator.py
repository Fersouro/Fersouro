"""Extracao de campos de PDFs por contexto (rotulo -> valor), dirigida por YAML.

Nada aqui "pega o primeiro numero do PDF": cada campo tem rotulos (regex) em
ordem de prioridade, e o valor e procurado logo depois do rotulo -- na mesma
linha ou, em layout de tabela, na linha de baixo, na coluna do rotulo.

Um PDF pode ter uma ou varias SGs: o texto e dividido em blocos por SG (o
campo ``chave`` do layout) e cada bloco vira um registro. Formatos diferentes
de relatorio viram ``layouts`` diferentes no YAML, escolhidos pela regex
``identificar``. Campo novo = mais uma entrada em ``campos``; nada de codigo.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .valores import ValorInvalido, chave_numerica, parse_brl

PADRAO_DINHEIRO = (
    r"\(?-?\s*(?:r\$\s*)?-?\s*(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}\)?(?:\s?-(?!\d))?"
)
PADRAO_DATA = r"\d{2}/\d{2}/\d{4}"
PADRAO_DOCUMENTO = r"\d[\d.\-/]{2,20}\d"

# o que pode ficar entre o rotulo e o valor na mesma linha
_SO_SEPARADORES = re.compile(r"[\s:=\-#.()\[\]/r$nº°o_*|]*")

PADROES_POR_TIPO = {
    "dinheiro": PADRAO_DINHEIRO,
    "data": PADRAO_DATA,
    "documento": PADRAO_DOCUMENTO,
    "texto": r"\S.*\S|\S",
}


class ErroExtracao(Exception):
    """PDF que nao deu para ler com seguranca (motivo vai para o log)."""


@dataclass(frozen=True)
class RegraCampo:
    nome: str
    tipo: str = "texto"
    rotulos: tuple[str, ...] = ()
    padrao: str | None = None
    obrigatorio: bool = False
    linhas_abaixo: int = 2
    min_digitos: int | None = None
    max_digitos: int | None = None

    @classmethod
    def from_dict(cls, nome: str, d: dict[str, Any]) -> "RegraCampo":
        tipo = d.get("tipo", "texto")
        if tipo not in PADROES_POR_TIPO:
            raise ValueError(f"campo '{nome}': tipo '{tipo}' invalido ({', '.join(PADROES_POR_TIPO)})")
        rotulos = d.get("rotulos") or []
        if isinstance(rotulos, str):
            rotulos = [rotulos]
        if not rotulos:
            raise ValueError(f"campo '{nome}': informe ao menos um rotulo")
        return cls(
            nome=nome,
            tipo=tipo,
            rotulos=tuple(_normalizar_regex(r) for r in rotulos),
            padrao=d.get("padrao"),
            obrigatorio=bool(d.get("obrigatorio", False)),
            linhas_abaixo=int(d.get("linhas_abaixo", 2)),
            min_digitos=d.get("min_digitos"),
            max_digitos=d.get("max_digitos"),
        )

    @property
    def regex_valor(self) -> re.Pattern[str]:
        return re.compile(self.padrao or PADROES_POR_TIPO[self.tipo], re.IGNORECASE)


@dataclass(frozen=True)
class Layout:
    nome: str
    chave: str
    campos: tuple[RegraCampo, ...]
    identificar: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Layout":
        nome = d.get("nome", "padrao")
        campos = tuple(RegraCampo.from_dict(k, v or {}) for k, v in (d.get("campos") or {}).items())
        if not campos:
            raise ValueError(f"layout '{nome}': sem campos")
        chave = d.get("chave") or campos[0].nome
        if chave not in {c.nome for c in campos}:
            raise ValueError(f"layout '{nome}': chave '{chave}' nao esta entre os campos")
        ident = d.get("identificar")
        return cls(nome=nome, chave=chave, campos=campos,
                   identificar=_normalizar_regex(ident) if ident else None)

    def campo(self, nome: str) -> RegraCampo:
        return next(c for c in self.campos if c.nome == nome)


@dataclass
class Resultado:
    layout: str
    registros: list[dict[str, Any]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# --------------------------------------------------------------- texto do PDF

def _sem_acento_minusculo(texto: str) -> str:
    """Minusculo e sem acento, preservando quebras de linha e colunas."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _normalizar_regex(regex: str) -> str:
    """Rotulos do YAML valem com ou sem acento/maiuscula: comparamos no texto normalizado."""
    return _sem_acento_minusculo(regex)


def validar_pdf(caminho: Path) -> int:
    """Confere que o arquivo e um PDF inteiro e legivel. Devolve o numero de paginas."""
    caminho = Path(caminho)
    if not caminho.is_file() or caminho.stat().st_size == 0:
        raise ErroExtracao("arquivo vazio ou inexistente")
    with caminho.open("rb") as f:
        inicio = f.read(1024)
        f.seek(max(0, caminho.stat().st_size - 2048))
        fim = f.read()
    if b"%PDF-" not in inicio:
        raise ErroExtracao("nao e um PDF (cabecalho %PDF ausente -- pode ser uma pagina de erro/HTML)")
    if b"%%EOF" not in fim:
        raise ErroExtracao("PDF incompleto (sem %%EOF no fim -- download interrompido?)")
    try:
        from pypdf import PdfReader

        paginas = len(PdfReader(str(caminho)).pages)
    except Exception as exc:  # noqa: BLE001 - qualquer falha do leitor = corrompido
        raise ErroExtracao(f"PDF corrompido: {exc}") from exc
    if paginas == 0:
        raise ErroExtracao("PDF sem paginas")
    return paginas


def texto_do_pdf(caminho: Path) -> str:
    """Texto do PDF, pagina a pagina. Tenta o modo 'layout' (mantem colunas)."""
    from pypdf import PdfReader

    try:
        leitor = PdfReader(str(caminho))
    except Exception as exc:  # noqa: BLE001
        raise ErroExtracao(f"nao consegui abrir o PDF: {exc}") from exc
    paginas = []
    for pagina in leitor.pages:
        texto = ""
        try:
            texto = pagina.extract_text(extraction_mode="layout") or ""
        except Exception:  # noqa: BLE001 - modo layout falha em alguns PDFs
            texto = ""
        if not texto.strip():
            texto = pagina.extract_text() or ""
        paginas.append(texto)
    completo = "\n".join(paginas)
    if not completo.strip():
        raise ErroExtracao("PDF sem texto (imagem escaneada?) -- precisa de OCR")
    return completo


# ------------------------------------------------------------------ extracao

def _converter(regra: RegraCampo, bruto: str) -> Any:
    bruto = bruto.strip()
    if regra.tipo == "dinheiro":
        return parse_brl(bruto)
    if regra.tipo == "data":
        return dt.datetime.strptime(bruto, "%d/%m/%Y").date()
    if regra.tipo == "documento":
        chave = chave_numerica(bruto)
        if not chave.isdigit():
            raise ValorInvalido(f"documento com letras: {bruto!r}")
        n = len(chave)
        if regra.min_digitos and n < int(regra.min_digitos):
            raise ValorInvalido(f"{bruto!r} tem {n} digitos (minimo {regra.min_digitos})")
        if regra.max_digitos and n > int(regra.max_digitos):
            raise ValorInvalido(f"{bruto!r} tem {n} digitos (maximo {regra.max_digitos})")
        return chave
    return bruto


def _valores_apos_rotulo(regra: RegraCampo, linhas: list[str], i: int, fim_rotulo: int,
                         col_rotulo: int) -> list[str]:
    """Candidatos para um rotulo na linha i: primeiro o resto da mesma linha;
    se nada, as linhas de baixo (valor na coluna do rotulo, layout de tabela)."""
    rx = regra.regex_valor
    m = rx.search(linhas[i], fim_rotulo)
    # Mesma linha so vale se entre o rotulo e o valor houver apenas separadores
    # ("SG: 123", "Total (R$) ..... 1.234,56"). Outra palavra no meio quer dizer
    # que o numero e de outro campo -- ai procura embaixo (tabela).
    if m and _SO_SEPARADORES.fullmatch(linhas[i][fim_rotulo:m.start()]):
        return [m.group(0)]
    for j in range(i + 1, min(len(linhas), i + 1 + regra.linhas_abaixo)):
        achados = list(rx.finditer(linhas[j]))
        if not achados:
            continue
        # valor mais perto da coluna em que o rotulo comeca
        melhor = min(achados, key=lambda a: abs(a.start() - col_rotulo))
        return [melhor.group(0)]
    return []


def _extrair_campo(regra: RegraCampo, linhas: list[str]) -> tuple[Any, list[str]]:
    """Valor do campo no bloco. Levanta ErroExtracao se ambiguo."""
    avisos: list[str] = []
    for rotulo in regra.rotulos:
        rx_rotulo = re.compile(rotulo, re.IGNORECASE)
        valores: list[Any] = []
        for i, linha in enumerate(linhas):
            for m in rx_rotulo.finditer(linha):
                for bruto in _valores_apos_rotulo(regra, linhas, i, m.end(), m.start()):
                    try:
                        valores.append(_converter(regra, bruto))
                    except (ValorInvalido, ValueError) as exc:
                        avisos.append(f"{regra.nome}: descartei {bruto.strip()!r} ({exc})")
        distintos = list(dict.fromkeys(valores))
        if len(distintos) == 1:
            return distintos[0], avisos
        if len(distintos) > 1:
            raise ErroExtracao(
                f"{regra.nome} ambiguo: o rotulo /{rotulo}/ aparece com valores diferentes "
                f"{[str(v) for v in distintos]}"
            )
    return None, avisos


def _blocos_por_chave(layout: Layout, linhas: list[str]) -> list[tuple[str, list[str]]]:
    """Divide o texto em blocos, um por valor distinto da chave (SG)."""
    regra = layout.campo(layout.chave)
    marcos: list[tuple[int, str]] = []  # (linha, valor)
    for rotulo in regra.rotulos:
        rx_rotulo = re.compile(rotulo, re.IGNORECASE)
        for i, linha in enumerate(linhas):
            for m in rx_rotulo.finditer(linha):
                for bruto in _valores_apos_rotulo(regra, linhas, i, m.end(), m.start()):
                    try:
                        marcos.append((i, _converter(regra, bruto)))
                    except (ValorInvalido, ValueError):
                        pass
        if marcos:
            break  # usa so o rotulo de maior prioridade que achou algo
    if not marcos:
        return []
    marcos.sort()
    blocos: list[tuple[str, list[str]]] = []
    inicio_por_valor: dict[str, int] = {}
    ordem: list[str] = []
    for linha, valor in marcos:
        if valor not in inicio_por_valor:
            inicio_por_valor[valor] = linha
            ordem.append(valor)
    for k, valor in enumerate(ordem):
        ini = 0 if k == 0 else inicio_por_valor[valor]
        fim = inicio_por_valor[ordem[k + 1]] if k + 1 < len(ordem) else len(linhas)
        blocos.append((valor, linhas[ini:fim]))
    return blocos


def escolher_layout(layouts: list[Layout], texto_normalizado: str) -> Layout:
    for layout in layouts:
        if layout.identificar and re.search(layout.identificar, texto_normalizado, re.IGNORECASE):
            return layout
    padrao = [l for l in layouts if not l.identificar]
    if padrao:
        return padrao[0]
    raise ErroExtracao("nenhum layout do YAML reconhece este PDF (ajuste 'identificar')")


def extrair_texto(texto: str, layouts: list[Layout]) -> Resultado:
    """Extrai os registros de um texto ja lido do PDF."""
    normal = _sem_acento_minusculo(texto)
    layout = escolher_layout(layouts, normal)
    linhas = normal.splitlines()
    resultado = Resultado(layout=layout.nome)

    blocos = _blocos_por_chave(layout, linhas)
    if not blocos:
        raise ErroExtracao(f"Nao foi possivel localizar o numero da {layout.chave.upper()}")

    for valor_chave, bloco in blocos:
        registro: dict[str, Any] = {layout.chave: valor_chave}
        for regra in layout.campos:
            if regra.nome == layout.chave:
                continue
            valor, avisos = _extrair_campo(regra, bloco)
            resultado.avisos.extend(f"{layout.chave} {valor_chave}: {a}" for a in avisos)
            if valor is None and regra.obrigatorio:
                raise ErroExtracao(
                    f"{regra.nome.replace('_', ' ').capitalize()} nao identificado "
                    f"({layout.chave.upper()} {valor_chave})"
                )
            registro[regra.nome] = valor
        resultado.registros.append(registro)
    return resultado


def extrair_pdf(caminho: Path, layouts: list[Layout]) -> Resultado:
    validar_pdf(caminho)
    return extrair_texto(texto_do_pdf(caminho), layouts)
