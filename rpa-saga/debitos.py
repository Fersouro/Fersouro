# -*- coding: utf-8 -*-
"""Auditoria dos fechamentos (.xls): debitos em aberto e erros de planilha. SO LEITURA.

    python debitos.py                 # todos os .xls de planilhas/ (e DRIVE_DIR, se houver)
    python debitos.py A.xls B.xls     # so estes

Debito = O.S. com NF emitida (VAL. NF. SERV. + VAL. NF. PECA) e credito VW menor
que a NF, somando os creditos de TODOS os fechamentos em que a O.S. aparece
(a VW costuma pagar em parcelas: "Diferenca sera paga no proximo fechamento").
A O.S. cuja ultima observacao diz "quitada" nao e debito (a parcela anterior pode
estar num mes que nao foi lido).

Tambem aponta erros que ja aconteceram nas planilhas reais:
  - valor com 3+ casas decimais (ex.: 101,173)
  - O.S. repetida no mesmo fechamento (linha em branco copiada)
  - linha de O.S. sem credito e sem NF (lista copiada de outro fechamento)
  - "sera paga no proximo" que nunca foi paga

Gera saida/debitos_*.csv. Nao altera nenhuma planilha.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from cruzar import SECOES, chave

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "saida"
MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
TOLERANCIA = 0.10  # centavos de arredondamento VW x NF (ex.: -0,06 e normal)


def sa(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def ordem(p: Path):
    """(ano, mes, numero) pelo nome 'Nº FECHAMENTO DE MES AAAA.xls'."""
    n = sa(p.name)
    num = re.search(r"(\d+)\s*[º°o]?\s*fechamento", n)
    ano = re.search(r"(20\d\d)", n)
    mes = next((i for i, m in enumerate(MESES, 1) if m in n), 0)
    return (int(ano.group(1)) if ano else 0, mes, int(num.group(1)) if num else 0)


def num(v) -> float:
    return v if isinstance(v, float) else 0.0


def ler(caminho: Path) -> list[dict]:
    import xlrd
    s = xlrd.open_workbook(str(caminho)).sheet_by_index(0)
    linhas, secao = [], "PRINCIPAL"
    for r in range(2, s.nrows):
        v = s.row_values(r) + [""] * 9
        a = v[0]
        txt = str(a).strip().upper()
        if txt in SECOES:
            secao = txt
            continue
        if not txt or txt.startswith("TOTAL"):
            continue
        linhas.append(dict(arq=caminho.name, lin=r + 1, secao=secao, os=chave(a),
                           serv=v[4], peca=v[5], cred=v[6], obs=str(v[8]).strip()))
    return linhas


def auditar(arquivos: list[Path]) -> tuple[list, list]:
    arquivos = sorted(arquivos, key=ordem)
    todas = [l for a in arquivos for l in ler(a)]
    erros = []
    vistos = defaultdict(list)
    for l in todas:
        for campo in ("serv", "peca", "cred"):
            if isinstance(l[campo], float) and abs(round(l[campo], 2) - l[campo]) > 1e-9:
                erros.append((l["arq"], l["lin"], l["os"], f"{campo} com 3+ casas decimais: {l[campo]}"))
        if l["cred"] == "" and l["serv"] == "" and l["peca"] == "":
            erros.append((l["arq"], l["lin"], l["os"], "O.S. sem credito e sem NF (linha copiada?)"))
        vistos[(l["arq"], l["os"])].append(l["lin"])
    for (arq, os_), lins in vistos.items():
        if len(lins) > 1:
            erros.append((arq, lins[0], os_, f"O.S. repetida no mesmo fechamento (linhas {lins})"))

    por_os = defaultdict(list)
    for l in todas:
        por_os[l["os"]].append(l)
    debitos = []
    for os_, ls in por_os.items():
        nf = max(num(l["serv"]) + num(l["peca"]) for l in ls)
        if nf <= 0:
            continue
        cred = sum(num(l["cred"]) for l in ls)
        falta = round(nf - cred, 2)
        ultima = next((l["obs"] for l in reversed(ls) if l["obs"]), "")
        if falta > TOLERANCIA and "quitad" not in sa(ultima):
            onde = "; ".join(f"{l['arq']} L{l['lin']}: {l['cred'] or '-'}" for l in ls)
            debitos.append((os_, round(nf, 2), round(cred, 2), falta, ultima, onde))
    debitos.sort(key=lambda d: -d[3])
    return debitos, erros


def main(argv: list[str]) -> int:
    arquivos = [Path(a) for a in argv if a.lower().endswith(".xls")]
    if not arquivos:
        pastas = [AQUI / "planilhas"]
        if os.environ.get("DRIVE_DIR"):
            pastas.append(Path(os.environ["DRIVE_DIR"]))
        arquivos = [p for d in pastas if d.exists() for p in d.rglob("*.xls")
                    if not p.name.startswith("~$") and "fechamento" in sa(p.name)]
    if not arquivos:
        print("Nenhum fechamento .xls encontrado.")
        return 1
    debitos, erros = auditar(arquivos)

    print(f"{len(arquivos)} fechamento(s) lido(s)\n")
    print(f"DEBITOS EM ABERTO: {len(debitos)}  |  total R$ {sum(d[3] for d in debitos):,.2f}"
          .replace(",", "X").replace(".", ",").replace("X", "."))
    for os_, nf, cred, falta, obs, _ in debitos:
        print(f"  {os_:>9}  NF {nf:>9.2f}  creditado {cred:>9.2f}  FALTA {falta:>9.2f}  {obs}")
    print(f"\nERROS NAS PLANILHAS: {len(erros)}")
    for arq, lin, os_, msg in erros:
        print(f"  {arq}  linha {lin}  O.S. {os_}: {msg}")

    SAIDA.mkdir(exist_ok=True)
    out = SAIDA / f"debitos_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["tipo", "os", "nf", "creditado", "falta", "observacao", "onde"])
        for d in debitos:
            w.writerow(["DEBITO", d[0], *(str(x).replace(".", ",") for x in d[1:4]), d[4], d[5]])
        for arq, lin, os_, msg in erros:
            w.writerow(["ERRO", os_, "", "", "", msg, f"{arq} linha {lin}"])
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
