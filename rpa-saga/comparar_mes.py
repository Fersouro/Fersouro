# -*- coding: utf-8 -*-
"""Portal Rede x Drive: quantos fechamentos o mes REALMENTE tem e quais faltam.
SO LEITURA -- nao cria pasta nem planilha.

    python comparar_mes.py                  # mes do relatorio mais recente
    python comparar_mes.py --ano 2026 --mes 9

Regra critica (docs/saga-vh47.md): nao existe "4 ou 5 por mes". O Portal Rede
(Lista de arquivos do SAGA2 - VH47, DN 1079) diz quantos fechamentos existem;
o Drive (os .xls da pasta planilhas/, ou DRIVE_DIR) diz quantos ja foram feitos.

  Portal : saida/lista_*.csv mais recente (gerado pelo RODAR.bat)
  Drive  : planilhas/*.xls  (ou DRIVE_DIR\\<ano>\\<Mes NN - Nome>\\*.xls)
  PDFs   : saida/pdfs/*.pdf (para conferir pelo CONTEUDO, nao so pelo numero)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "saida"
MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


def sa(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def portal_do_mes(ano: int | None, mes: int | None, dn: str):
    from saga_rpa import data_relatorio
    listas = sorted(SAIDA.glob("lista_*.csv"))
    if not listas:
        return None, None, None, "nenhuma lista lida do Portal (rode RODAR.bat)"
    with open(listas[-1], encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    col = {sa(k): k for k in (linhas[0].keys() if linhas else [])}
    c_ano, c_mes, c_dn = col.get("ano"), col.get("mes"), col.get("dn")
    c_nome = next((v for k, v in col.items() if "arquivo" in k or "nome" in k), None)
    if not all([c_ano, c_mes, c_dn, c_nome]):
        return None, None, None, f"a lista {listas[-1].name} nao tem as colunas Ano/Mes/DN/Nome"
    meus = [l for l in linhas if re.sub(r"\D", "", l[c_dn]).lstrip("0") == dn]
    if not meus:
        return None, None, None, f"nenhum arquivo do DN {dn} na lista"

    def ref(l):
        return int(re.sub(r"\D", "", l[c_ano])), int(re.sub(r"\D", "", l[c_mes]))
    if ano is None:  # mes de referencia = o do relatorio mais recente (nao o relogio)
        mais_novo = max(meus, key=lambda l: data_relatorio(l[c_nome], l[c_ano], l[c_mes]))
        ano, mes = ref(mais_novo)
    do_mes = [l for l in meus if ref(l) == (ano, mes)]
    do_mes.sort(key=lambda l: data_relatorio(l[c_nome], l[c_ano], l[c_mes]))
    nomes = [l[c_nome] for l in do_mes]
    dup = {n for n in nomes if nomes.count(n) > 1}
    if dup:
        return ano, mes, None, f"arquivo repetido na lista do Portal: {', '.join(dup)}"
    return ano, mes, nomes, None


def drive_do_mes(ano: int, mes: int) -> dict:
    """{numero: Path} dos fechamentos do mes no Drive (pelo nome e pela linha 1)."""
    import xlrd
    base = os.environ.get("DRIVE_DIR")
    pastas = [AQUI / "planilhas"]
    if base:
        pastas += [p for p in (Path(base) / str(ano)).glob("*") if p.is_dir() and
                   (f"{mes:02d}" in p.name or MESES[mes - 1] in sa(p.name))]
    achados: dict[int, list[Path]] = {}
    for pasta in pastas:
        for x in pasta.glob("*.xls"):
            if x.name.startswith("~$"):
                continue
            n_nome = re.search(r"(\d+)\s*[º°o]?\s*fechamento", sa(x.name))
            if not n_nome or MESES[mes - 1] not in sa(x.name) or str(ano) not in x.name:
                continue
            try:  # confere pela linha 1 da planilha: "Nº Fechamento | Mes de AAAA"
                l1 = sa(" ".join(str(v) for v in xlrd.open_workbook(str(x)).sheet_by_index(0).row_values(0)))
                n_l1 = re.search(r"(\d+)\s*[º°o]?\s*fechamento", l1)
                if n_l1 and int(n_l1.group(1)) != int(n_nome.group(1)):
                    print(f"  ATENCAO: {x.name} diz {n_l1.group(1)}º na linha 1")
            except Exception:
                pass
            achados.setdefault(int(n_nome.group(1)), []).append(x)
    return achados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int)
    ap.add_argument("--mes", type=int)
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(AQUI / ".env")
    except ImportError:
        pass
    dn = os.environ.get("DN", "1079").lstrip("0")

    ano, mes, portal, erro = portal_do_mes(a.ano, a.mes, dn)
    if erro:
        print("STATUS: NECESSITA CONFERENCIA\n" + erro)
        return 2
    drive = drive_do_mes(ano, mes)
    print(f"Mes de referencia: {MESES[mes - 1].capitalize()}/{ano}  (DN {dn})")
    print(f"\nPORTAL REDE\nFechamentos encontrados: {len(portal)}")
    for i, n in enumerate(portal, 1):
        print(f"  {i}: {n}")
    print(f"\nDRIVE\nFechamentos existentes: {len(drive)}")
    for k in sorted(drive):
        print(f"  {k}º: {', '.join(p.name for p in drive[k])}")

    # conferencia pelo CONTEUDO: SGs do PDF dentro do fechamento de mesmo numero
    import cruzar
    import vh47
    status, novos, conferir = [], [], []
    for i, nome in enumerate(portal, 1):
        pdf = SAIDA / "pdfs" / nome
        arqs = drive.get(i, [])
        if len(arqs) > 1:
            conferir.append(f"{i}º: mais de um arquivo no Drive ({', '.join(p.name for p in arqs)})")
            continue
        if not arqs:
            novos.append(f"{i}º  <- {nome}")
            continue
        if not pdf.exists():
            status.append(f"{i}º: existe no Drive (conteudo nao conferido: PDF nao baixado)")
            continue
        rel = vh47.ler(pdf)
        pl = cruzar.ler_planilha(arqs[0])
        tem = sum(1 for s in rel.sgs if cruzar.chave(s) in pl)
        if tem == len(rel.sgs):
            status.append(f"{i}º: processado ({tem}/{len(rel.sgs)} SGs na planilha)")
        elif tem == 0:
            outro = [k for k, ps in drive.items() if k != i and
                     sum(1 for s in rel.sgs if cruzar.chave(s) in cruzar.ler_planilha(ps[0])) > len(rel.sgs) // 2]
            if outro:
                conferir.append(f"{i}º: as SGs de {nome} estao no {outro[0]}º do Drive (numeracao diferente)")
            else:
                novos.append(f"{i}º  <- {nome} (planilha existe, mas vazia)")
        else:
            conferir.append(f"{i}º: so {tem} de {len(rel.sgs)} SGs de {nome} estao na planilha")
    sobra = [k for k in drive if k > len(portal)]
    for k in sobra:
        conferir.append(f"{k}º existe no Drive mas NAO existe no Portal Rede")

    print("\nRESULTADO:")
    for s in status:
        print("  " + s)
    if conferir:
        print("STATUS: NECESSITA CONFERENCIA")
        for c in conferir:
            print("  " + c)
    if novos:
        print(f"Existe(m) {len(novos)} novo(s) fechamento(s) para processar:")
        for n in novos:
            print("  " + n)
    if not novos and not conferir:
        print("Todos os fechamentos ja foram processados." if drive else "Nenhum fechamento no Drive.")
    return 2 if conferir else 0


if __name__ == "__main__":
    sys.exit(main())
