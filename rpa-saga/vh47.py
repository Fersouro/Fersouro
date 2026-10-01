# -*- coding: utf-8 -*-
"""Leitura do relatorio VH47A ("RELACAO DOS CREDITOS PROCESSADOS") do SAGA2.

Cada bloco do PDF e uma SG:  NUMERO O.S | SR | VR | TG | ... | TOTAL M.OBRA |
TOTAL MATERIAL | TOTAL SG.  O "Resumo" no fim traz o TOTAL SGS.

Regras (docs/saga-vh47.md do datalake):
  * a mesma O.S. com mais de uma versao (SR 01, 02...) -> SOMA na mesma linha;
  * O.S. com "A" no fim (214265A) e valida e diferente da sem "A";
  * TG 1S1/1S2/1S3 = revisao -> secao REVISOES; o resto -> secao principal;
  * conferencias: M.OBRA + MATERIAL = TOTAL SG em cada bloco, e a soma dos
    TOTAL SG = TOTAL SGS do resumo. Se nao bater, o PDF nao e aceito.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

BLOCO = re.compile(
    r"\*\s*(\d{5,7}[A-Z]?)\s*\*\s*(\d\d)\s*\*\s*(\d\d)\s*\*\s*(\S+)\s*\*\s*(\S+)\s*\*\s*(\S+)\s*\*\s*(\S+)\s*\*"
    r"\s*([\d.]+)\s*\*\s*([\d.]+)\s*\*\s*(\d+)\s*\*\s*(\S+)\s*\*\s*([\d.,]+)\s*\*\s*([\d.,]+)\s*\*\s*([\d.,]+)\s*\*")
RESUMO = re.compile(r"TOT\.:\s*(\d+)\s+.*?([\d.]+,\d\d)\s*\*", re.S)


def valor(txt: str) -> Decimal:
    """'1.234,56' -> Decimal('1234.56')"""
    return Decimal(txt.replace(".", "").replace(",", "."))


@dataclass
class SG:
    os: str
    versoes: list = field(default_factory=list)  # [(SR, VR, TG, total)]

    @property
    def total(self) -> Decimal:
        return sum((v[3] for v in self.versoes), Decimal("0"))

    @property
    def revisao(self) -> bool:
        return any(v[2].upper().startswith("1S") for v in self.versoes)


@dataclass
class Relatorio:
    arquivo: str
    periodo: str = ""
    dn: str = ""
    lancamento: str = ""
    processado: str = ""
    sgs: dict = field(default_factory=dict)  # os -> SG
    total_resumo: Decimal | None = None
    blocos: int = 0

    @property
    def total(self) -> Decimal:
        return sum((s.total for s in self.sgs.values()), Decimal("0"))


def texto_pdf(caminho: Path) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(caminho)).pages)


def ler(caminho: Path) -> Relatorio:
    t = texto_pdf(caminho)
    if "VH47" not in t:
        raise ValueError("nao parece um relatorio VH47")
    r = Relatorio(arquivo=Path(caminho).name)
    m = re.search(r"PERIODO:\s*([\d.]+\s*A\s*[\d.]+)", t)
    r.periodo = m.group(1) if m else ""
    m = re.search(r"DN:\s*(\d+)", t)
    r.dn = m.group(1).lstrip("0") if m else ""
    m = re.search(r"NUM\.LANCAMENTO:\s*([\d.]+)", t)
    r.lancamento = m.group(1) if m else ""
    m = re.search(r"DATA DO PROCESSAMENTO:\s*([\d.]+)", t)
    r.processado = m.group(1) if m else ""

    for b in BLOCO.findall(t):
        os_, sr, vr, tg = b[0], b[1], b[2], b[3]
        mo, mat, tot = valor(b[11]), valor(b[12]), valor(b[13])
        if mo + mat != tot:
            raise ValueError(f"O.S. {os_} SR {sr}: M.OBRA + MATERIAL ({mo + mat}) diferente do TOTAL SG ({tot})")
        r.sgs.setdefault(os_, SG(os_)).versoes.append((sr, vr, tg, tot))
        r.blocos += 1
    if not r.sgs:
        raise ValueError("nenhuma SG encontrada no PDF")

    m = RESUMO.search(t)
    if m:
        r.total_resumo = valor(m.group(2))
        if r.total_resumo != r.total:
            raise ValueError(f"soma das SGs ({r.total}) diferente do TOTAL SGS do resumo ({r.total_resumo})")
    return r
