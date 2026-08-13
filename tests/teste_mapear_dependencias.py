#!/usr/bin/env python3
"""Testes do relatorio de dependencias, sem tocar o BigQuery.

Existe por causa de um erro real: a primeira versao identificava escrita por
`destination_table IS NOT NULL`, e o BigQuery deixa esse campo nulo em jobs
LOAD. Rodado contra o projeto de verdade, o relatorio dizia "nenhuma escrita
registrada" num projeto com 7.020 LOADs em dez dias — e dizia isso na secao
que decide o que precisa ser congelado antes da verificacao valer.

Um falso negativo que se le como tranquilidade e o pior defeito possivel num
relatorio de risco. Os casos abaixo reproduzem a forma dos dados reais para
que esse especifico nao volte.

  python tests/teste_mapear_dependencias.py
"""

import datetime as dt
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

from mapear_dependencias import (  # noqa: E402
    CONDICAO_ESCRITA,
    dialeto,
    maior_janela_ociosa,
    montar_relatorio,
)

COMPUTE = "370559798304-compute@developer.gserviceaccount.com"
PORTAL = "portal-relatorios@tterrasul-datalake.iam.gserviceaccount.com"
FERNANDO = "fernando@tterrasul.com.br"


def T(dia: int) -> dt.datetime:
    return dt.datetime(2026, 8, dia, tzinfo=dt.timezone.utc)


# Forma real do projeto: o pipeline escreve por LOAD, que nao registra destino.
REAL = {
    "principais": [
        {"user_email": COMPUTE, "job_type": "LOAD", "jobs": 7020,
         "jobs_com_erro": 0, "primeiro": T(3), "ultimo": T(13),
         "bytes_processados": 0},
        {"user_email": FERNANDO, "job_type": "QUERY", "jobs": 836,
         "jobs_com_erro": 9, "primeiro": T(3), "ultimo": T(13),
         "bytes_processados": 10**11},
        {"user_email": PORTAL, "job_type": "QUERY", "jobs": 101,
         "jobs_com_erro": 1, "primeiro": T(10), "ultimo": T(12),
         "bytes_processados": 10**9},
    ],
    "leituras": (
        [{"user_email": PORTAL, "dataset_id": "lake", "table_id": f"t{i}",
          "jobs": 18, "ultimo": T(12)} for i in range(23)]
        + [{"user_email": FERNANDO, "dataset_id": "gold", "table_id": "v1",
            "jobs": 90, "ultimo": T(13)}]
    ),
    "escritas": [
        {"user_email": COMPUTE, "job_type": "LOAD", "statement_type": None,
         "dataset_id": None, "tabelas": 0, "jobs": 7020, "ultimo": T(13),
         "job_exemplo": "bqjob_r1a2b3c4"},
        {"user_email": FERNANDO, "job_type": "QUERY", "statement_type": "MERGE",
         "dataset_id": "gold", "tabelas": 2, "jobs": 4, "ultimo": T(10),
         "job_exemplo": "bqjob_rZZZ"},
    ],
    "horario_das_escritas": [{"hora": h, "jobs": 900 if h == 2 else 30}
                             for h in range(6)],
    "dialeto_por_principal": {
        FERNANDO: {"consultas": 383, "divergentes": 78},
        PORTAL: {"consultas": 46, "divergentes": 27},
    },
    "construcoes": {"FORMAT_DATE usa formato diferente (strftime)": 68,
                    "SAFE_DIVIDE nao existe no DuckDB": 44},
}

VAZIO = {"principais": [], "leituras": [], "escritas": [],
         "horario_das_escritas": [], "dialeto_por_principal": {},
         "construcoes": {}}

falhas: list[str] = []


def checa(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def trecho(texto: str, titulo: str, n: int = 500) -> str:
    i = texto.index(titulo)
    return texto[i:i + n]


def main() -> int:
    print("== a regressao que originou este teste ==")
    checa("LOAD" in CONDICAO_ESCRITA,
          "LOAD conta como escrita na condicao SQL")
    checa("destination_table" not in CONDICAO_ESCRITA,
          "a condicao nao depende de destination_table")

    r = montar_relatorio(REAL, "tterrasul-datalake", 180)
    checa("Nenhuma escrita registrada" not in r,
          "projeto com 7.020 LOADs nao e reportado como sem escritas")
    checa("7,020" in r, "o volume de LOAD aparece")

    print("\n== leitor x escritor pedem acoes opostas ==")
    puros = trecho(r, "Consomem e nao escrevem")
    mistos = trecho(r, "Consultam e tambem escrevem")
    checa(PORTAL in puros, "o portal e consumidor puro: reapontar")
    checa(FERNANDO in mistos, "quem le e escreve nao entra como consumidor puro")
    checa(COMPUTE not in puros,
          "o pipeline nunca aparece na lista de reapontar para o DuckDB")

    print("\n== destino ausente e dito, nao omitido ==")
    checa("nao registrado" in r, "linha de LOAD marca o destino como ausente")
    checa("bqjob_r1a2b3c4" in r, "entrega o job_id para investigar")
    checa("bq show" in r, "diz como investigar")

    print("\n== janela de exportacao ==")
    checa("Pico as 02h" in r, "identifica o horario de pico")
    checa("06h" in trecho(r, "Horas sem nenhuma escrita", 300),
          "lista as horas ociosas")

    # O dia da a volta: 21h-04h sao 8 horas seguidas, nao duas janelas.
    checa(maior_janela_ociosa({5, 8, 9, 10, 11, 14, 15, 16, 17, 19, 20}) == (21, 8),
          "acha a janela que cruza a meia-noite (caso real do projeto)")
    checa(maior_janela_ociosa(set(range(24))) is None,
          "projeto que escreve o dia todo nao tem janela")
    checa(maior_janela_ociosa(set()) == (0, 24), "projeto parado: dia inteiro")
    checa(maior_janela_ociosa({0}) == (1, 23), "uma unica hora ocupada")
    checa(maior_janela_ociosa({0, 12})[1] == 11, "escolhe a maior das duas metades")

    print("\n== caso vazio nao quebra ==")
    v = montar_relatorio(VAZIO, "tterrasul-datalake", 30)
    checa("Nenhum job na janela" in v, "relata projeto ocioso sem estourar")

    print("\n== varredura de dialeto ==")
    checa(dialeto("SELECT SAFE_DIVIDE(a,b) FROM t") != [], "acha SAFE_DIVIDE")
    checa(dialeto("SELECT format_date('%Y', d) FROM t") != [],
          "acha FORMAT_DATE em minusculas")
    checa(dialeto("SELECT a FROM t") == [], "nao inventa achado em SQL simples")

    print("\n" + ("TODOS OS TESTES PASSARAM" if not falhas
                  else f"{len(falhas)} FALHA(S)"))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
