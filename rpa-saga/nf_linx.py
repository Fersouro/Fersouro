# -*- coding: utf-8 -*-
"""Busca no datalake (ERP Linx) as NFs das O.S. do relatorio VH47. SO LEITURA.

    python nf_linx.py
      - relatorio: o mais recente em saida/pdfs
      - calibracao: os .xls JA PREENCHIDOS na pasta planilhas/ (ex.: 1º e 2º do mes)
      - datalake: C:\\datalake\\lake.duckdb (ou DATALAKE_DB no .env)

1) CALIBRA: nas planilhas ja preenchidas, descobre de que tipo de nota
   (tipo_transacao) saem a "Nº NF S." e a "Nº NF P." e qual data/valor bate.
2) Para cada O.S. do relatorio, busca as notas do mesmo contato no Linx.
Gera saida/nf_linx.csv e mostra na tela para copiar.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

import vh47
from cruzar import chave

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "saida"


def base_os(os_) -> int | None:
    """214265A -> 214265 (a letra e relancamento manual da mesma O.S.)."""
    m = re.match(r"(\d+)", chave(os_))
    return int(m.group(1)) if m else None


def notas_por_os(con, lista_os: list[int]) -> dict:
    """{nro_os: [(tipo, nf, serie, data, total, status)]} pelas notas do mesmo contato."""
    if not lista_os:
        return {}
    ids = ",".join(str(int(o)) for o in set(lista_os))
    sql = f"""
        SELECT os.nro_os, fmc.tipo_transacao, fmc.numero_nota_fiscal, fmc.serie_nota_fiscal,
               CAST(fmc.dta_documento AS DATE), CAST(fmc.tot_nota_fiscal AS DOUBLE), fmc.status
          FROM silver.ccm__ofi_ordem_servico os
          JOIN silver.ccm__fat_movimento_capa fmc
            ON fmc.contato = os.contato AND fmc.empresa = os.empresa AND fmc.revenda = os.revenda
         WHERE os.nro_os IN ({ids})
    """
    res = {}
    for r in con.execute(sql).fetchall():
        res.setdefault(int(r[0]), []).append(tuple(r[1:]))
    return res


def ler_referencia(caminho: Path) -> list[dict]:
    """Linhas preenchidas de um fechamento: OS, NF P, NF S, data, val serv, val peca."""
    import xlrd
    wb = xlrd.open_workbook(str(caminho))
    s = wb.sheet_by_index(0)
    out = []
    for r in range(2, s.nrows):
        a = s.cell_value(r, 0)
        if a in ("", None) or str(a).strip().upper().startswith(("TOTAL", "REVIS", "RECONS", "LOCA")):
            continue
        nfp, nfs = s.cell_value(r, 1), s.cell_value(r, 2)
        if nfp == "" and nfs == "":
            continue
        out.append({"os": base_os(a), "nfp": nfp, "nfs": nfs})
    return out


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(AQUI / ".env")
    except ImportError:
        pass
    import duckdb
    db = os.environ.get("DATALAKE_DB", r"C:\datalake\lake.duckdb")
    con = duckdb.connect(db, read_only=True)

    from saga_rpa import data_relatorio
    pdfs = sorted((SAIDA / "pdfs").glob("*.pdf"), key=lambda p: (data_relatorio(p.name), p.stat().st_mtime))
    if not pdfs:
        print("ERRO: nenhum PDF em saida/pdfs (rode RODAR.bat --baixar)")
        return 1
    rel = vh47.ler(pdfs[-1])
    print(f"Relatorio: {rel.arquivo} | {len(rel.sgs)} SGs | credito {rel.total}")

    # ---- 1) calibracao com os fechamentos ja preenchidos
    ref = []
    for x in sorted((AQUI / "planilhas").glob("*.xls")):
        linhas = ler_referencia(x)
        if linhas:
            print(f"Calibrando com: {x.name} ({len(linhas)} linhas preenchidas)")
            ref += linhas
    tipo_s, tipo_p = Counter(), Counter()
    if ref:
        notas = notas_por_os(con, [l["os"] for l in ref if l["os"]])
        for l in ref:
            for (tipo, nf, serie, data, total, status) in notas.get(l["os"], []):
                if l["nfs"] != "" and str(int(float(l["nfs"]))) == str(nf):
                    tipo_s[tipo] += 1
                if l["nfp"] != "" and str(int(float(l["nfp"]))) == str(nf):
                    tipo_p[tipo] += 1
        print(f"  NF S. vem do tipo: {dict(tipo_s)}")
        print(f"  NF P. vem do tipo: {dict(tipo_p)}")
    ts = tipo_s.most_common(1)[0][0] if tipo_s else "O21"
    tp = tipo_p.most_common(1)[0][0] if tipo_p else None
    if not tipo_p:
        print("  AVISO: sem calibracao para NF de pecas (coloque em planilhas/ um fechamento ja preenchido)")

    # ---- 2) notas das O.S. do relatorio
    notas = notas_por_os(con, [base_os(o) for o in rel.sgs])
    linhas = []
    for os_, sg in rel.sgs.items():
        ns = notas.get(base_os(os_), [])
        s_ = [n for n in ns if n[0] == ts]
        p_ = [n for n in ns if tp and n[0] == tp]
        def um(lst):
            if len(lst) == 1:
                return lst[0], ""
            if not lst:
                return None, "sem nota"
            return sorted(lst, key=lambda n: n[3] or "")[-1], f"{len(lst)} notas (usei a mais recente)"
        ns_, obs_s = um(s_)
        np_, obs_p = um(p_)
        linhas.append({
            "os": os_, "secao": "REVISOES" if sg.revisao else "PRINCIPAL",
            "nf_p": np_[1] if np_ else "", "nf_s": ns_[1] if ns_ else "",
            "data": (ns_[3] or np_[3]).strftime("%d/%m/%Y") if (ns_ or np_) else "",
            "val_serv": f"{ns_[4]:.2f}" if ns_ else "", "val_peca": f"{np_[4]:.2f}" if np_ else "",
            "credito": f"{sg.total:.2f}", "obs": "; ".join(o for o in (obs_s and "S: " + obs_s, obs_p and "P: " + obs_p) if o),
        })
    SAIDA.mkdir(exist_ok=True)
    arq = SAIDA / "nf_linx.csv"
    with open(arq, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    print(f"\n--- COPIE DAQUI ATE O FIM ---")
    print(open(arq, encoding="utf-8-sig").read())
    print(f"--- FIM ({arq}) ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
