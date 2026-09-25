# -*- coding: utf-8 -*-
"""Cruza o PDF VH47 com a(s) planilha(s) de fechamento (.xls). SO LEITURA.

    python cruzar.py                         # PDF mais novo de saida/pdfs x planilhas/*.xls
    python cruzar.py RELATORIO.pdf A.xls B.xls

Para cada SG do PDF (versoes da mesma O.S. somadas) diz:
    OK              -> esta na planilha com o mesmo credito
    VALOR DIFERENTE -> esta, mas o VALOR CREDITO nao bate
    FALTA           -> nao esta em nenhuma planilha informada
E lista O.S. que estao na planilha mas nao no PDF.
Gera saida/cruzamento_*.csv. Nao altera nenhuma planilha.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import sys
from decimal import Decimal
from pathlib import Path

import vh47

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "saida"
SECOES = ("REVISÕES", "REVISOES", "RECONSIDERAÇÃO DE GARANTIAS", "RECONSIDERACAO DE GARANTIAS", "LOCAÇÕES", "LOCACOES")


def chave(os_) -> str:
    """212.646A / 212646a / 212646.0 -> 212646A (so para comparar)."""
    if isinstance(os_, float) and os_.is_integer():
        os_ = int(os_)
    t = re.sub(r"[\s.\-/]", "", str(os_)).upper()
    return (t.lstrip("0") or "0") if t else ""


def ler_planilha(caminho: Path) -> dict:
    """{chave_os: [(secao, linha_excel, credito)]} da aba de fechamento."""
    import xlrd
    wb = xlrd.open_workbook(str(caminho))
    s = wb.sheet_by_index(0)
    # acha o cabecalho: linha com "Nº OS" e "VALOR CRÉDITO"
    lin_cab, col_os, col_cred = None, 0, 6
    for r in range(min(10, s.nrows)):
        vals = [str(v).strip().upper() for v in s.row_values(r)]
        if any("OS" == v.replace("Nº", "").replace("N°", "").strip() or v.startswith("Nº OS") for v in vals):
            lin_cab = r
            for c, v in enumerate(vals):
                if "OS" in v and c < 3:
                    col_os = c
                if "CRÉDITO" in v or "CREDITO" in v:
                    col_cred = c
            break
    if lin_cab is None:
        raise ValueError(f"{caminho.name}: nao achei o cabecalho 'Nº OS'")
    dados, secao = {}, "PRINCIPAL"
    for r in range(lin_cab + 1, s.nrows):
        a = s.cell_value(r, col_os)
        txt = str(a).strip().upper()
        if txt in SECOES:
            secao = txt
            continue
        if not txt or txt.startswith("TOTAL"):
            continue
        cred = s.cell_value(r, col_cred)
        cred = Decimal(str(round(cred, 2))) if isinstance(cred, float) else None
        dados.setdefault(chave(a), []).append((secao, r + 1, cred))
    return dados


def main(argv: list[str]) -> int:
    pdfs = [Path(a) for a in argv if a.lower().endswith(".pdf")]
    xls = [Path(a) for a in argv if a.lower().endswith((".xls", ".xlsx"))]
    if not pdfs:
        todos = sorted((SAIDA / "pdfs").glob("*.pdf"), key=lambda p: p.stat().st_mtime)
        pdfs = todos[-1:]
    if not xls:
        xls = sorted((AQUI / "planilhas").glob("*.xls"))
    if not pdfs:
        print("ERRO: nenhum PDF (rode RODAR.bat --baixar ou informe o PDF)")
        return 1
    if not xls:
        print("ERRO: nenhuma planilha. Coloque os .xls do mes na pasta 'planilhas' desta pasta.")
        return 1

    rel = vh47.ler(pdfs[0])
    print(f"PDF: {rel.arquivo}")
    print(f"  periodo {rel.periodo} | DN {rel.dn} | lancamento {rel.lancamento} | processado {rel.processado}")
    print(f"  {rel.blocos} blocos -> {len(rel.sgs)} SGs (versoes somadas) | total {rel.total} (resumo do PDF: {rel.total_resumo})")

    planilhas = {p.name: ler_planilha(p) for p in xls}
    linhas, n = [], {"OK": 0, "VALOR DIFERENTE": 0, "FALTA": 0}
    for sg in rel.sgs.values():
        k = chave(sg.os)
        achou = [(nome, sec, lin, cred) for nome, d in planilhas.items() for (sec, lin, cred) in d.get(k, [])]
        secao_pdf = "REVISÕES" if sg.revisao else "PRINCIPAL"
        versoes = " + ".join(f"SR{v[0]}={v[3]}" for v in sg.versoes)
        if not achou:
            st, onde, cred = "FALTA", "", ""
        else:
            igual = [a for a in achou if a[3] == sg.total]
            a = (igual or achou)[0]
            st = "OK" if igual else "VALOR DIFERENTE"
            onde, cred = f"{a[0]} | {a[1]} | linha {a[2]}", a[3]
        n[st] += 1
        linhas.append({"OS": sg.os, "secao_pdf": secao_pdf, "versoes": versoes, "credito_pdf": sg.total,
                       "status": st, "onde_na_planilha": onde, "credito_planilha": cred})

    so_planilha = []
    chaves_pdf = {chave(s) for s in rel.sgs}
    for nome, d in planilhas.items():
        for k, ocorr in d.items():
            if k not in chaves_pdf:
                so_planilha += [(nome, k, sec, lin, cred) for (sec, lin, cred) in ocorr]

    SAIDA.mkdir(exist_ok=True)
    arq = SAIDA / f"cruzamento_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(arq, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";")
        w.writeheader()
        w.writerows(linhas)
        for nome, k, sec, lin, cred in so_planilha:
            w.writerow({"OS": k, "status": "SO NA PLANILHA", "onde_na_planilha": f"{nome} | {sec} | linha {lin}",
                        "credito_planilha": cred})

    print(f"\nPlanilhas: {', '.join(planilhas)}")
    print(f"  OK: {n['OK']}   VALOR DIFERENTE: {n['VALOR DIFERENTE']}   FALTA NA PLANILHA: {n['FALTA']}"
          f"   SO NA PLANILHA: {len(so_planilha)}")
    for l in linhas:
        if l["status"] != "OK":
            print(f"  {l['status']:15} O.S. {l['OS']:8} credito PDF {l['credito_pdf']:>9}  {l['onde_na_planilha']}"
                  f"{'  (planilha: ' + str(l['credito_planilha']) + ')' if l['status'] == 'VALOR DIFERENTE' else ''}")
    print(f"\nCREDITO TOTAL do relatorio: R$ {rel.total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    print(f"Detalhe: {arq}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
