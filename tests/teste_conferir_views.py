#!/usr/bin/env python3
"""Prova que conferir_views.py pega uma traducao que muda resultado em silencio.

Um verificador em que ninguem confere nada e so mais uma coisa para acreditar.
Este teste constroi o erro que o documento de migracao descreve — o
`SAFE_DIVIDE` "consertado" com COALESCE(...,0) e o `PARSE_DATE` com o formato
trocado — e exige que a comparacao acuse. Depois constroi a traducao certa e
exige que ela passe, porque um verificador que reclama de tudo tambem nao
serve.

Os dois lados sao DuckDB: o BigQuery nao esta ao alcance de uma bateria de
testes, e o que esta sob teste e a comparacao de perfis, que e o mesmo codigo
nos dois casos. A "origem" reproduz a semantica do BigQuery a mao.

Precisa so do duckdb instalado.

  python tests/teste_conferir_views.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(RAIZ, "scripts")
CONFERIR = os.path.join(SCRIPTS, "conferir_views.py")
sys.path.insert(0, SCRIPTS)

DADOS = """
CREATE SCHEMA gold;
CREATE TABLE gold.vendas (id INTEGER, valor DOUBLE, qtd INTEGER,
                          data_txt VARCHAR, regiao VARCHAR, ativo BOOLEAN);
INSERT INTO gold.vendas VALUES
  (1, 100.0, 4, '05/03/2026', 'sul',   true),
  (2, 250.0, 0, '11/07/2026', 'norte', false),
  (3, 90.0,  3, '02/09/2026', 'sul',   true),
  (4, 400.0, 0, '05/03/2026', 'leste', true),
  (5, 60.0,  2, '11/07/2026', 'norte', false);
"""
# As datas sao todas ambiguas de proposito (dia e mes <= 12). Trocar o formato
# nao levanta erro nenhum: so devolve outra data. E esse o ponto.

# Semantica do BigQuery escrita a mao: SAFE_DIVIDE devolve NULL quando o
# divisor e zero, e PARSE_DATE('%d/%m/%Y', ...) le o dia antes do mes.
ORIGEM = """
CREATE VIEW gold.vw_resumo AS
SELECT regiao,
       CASE WHEN qtd = 0 THEN NULL ELSE valor / qtd END AS ticket,
       strptime(data_txt, '%d/%m/%Y')::DATE AS dia,
       ativo
FROM gold.vendas;
CREATE VIEW gold.vw_por_regiao AS
SELECT regiao, COUNT(*) AS n, SUM(valor) AS total
FROM gold.vendas GROUP BY regiao;
"""

# Os dois erros do documento, juntos. Nenhum deles falha ao rodar.
DESTINO_ERRADO = """
CREATE VIEW gold.vw_resumo AS
SELECT regiao,
       COALESCE(valor / NULLIF(qtd, 0), 0) AS ticket,
       strptime(data_txt, '%m/%d/%Y')::DATE AS dia,
       ativo
FROM gold.vendas;
CREATE VIEW gold.vw_por_regiao AS
SELECT regiao, COUNT(*) AS n, SUM(valor) AS total
FROM gold.vendas GROUP BY regiao;
"""

# A mesma semantica, agora escrita corretamente no dialeto do DuckDB.
DESTINO_CERTO = """
CREATE VIEW gold.vw_resumo AS
SELECT regiao,
       TRY_CAST(valor AS DOUBLE) / NULLIF(qtd, 0) AS ticket,
       strptime(data_txt, '%d/%m/%Y')::DATE AS dia,
       ativo
FROM gold.vendas;
CREATE VIEW gold.vw_por_regiao AS
SELECT regiao, COUNT(*) AS n, SUM(valor) AS total
FROM gold.vendas GROUP BY regiao;
"""

# Uma view que nao chegou e uma coluna a mais: divergencia estrutural.
DESTINO_INCOMPLETO = """
CREATE VIEW gold.vw_resumo AS
SELECT regiao,
       CASE WHEN qtd = 0 THEN NULL ELSE valor / qtd END AS ticket,
       strptime(data_txt, '%d/%m/%Y')::DATE AS dia,
       ativo,
       'extra' AS coluna_nova
FROM gold.vendas;
"""

falhas: list[str] = []


def checa(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def montar(base: str, nome: str, ddl: str) -> str:
    import duckdb

    caminho = os.path.join(base, nome)
    con = duckdb.connect(caminho)
    con.execute(DADOS)
    for stmt in filter(str.strip, ddl.split(";")):
        con.execute(stmt)
    con.close()
    return caminho


def rodar(*args: str) -> tuple[int, str, str]:
    r = subprocess.run([sys.executable, CONFERIR, *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    try:
        import duckdb  # noqa: F401
    except ImportError:
        print("erro: duckdb nao instalado. Rode: pip install duckdb", file=sys.stderr)
        return 2

    base = tempfile.mkdtemp(prefix="conferir-views-")
    try:
        origem = montar(base, "origem.duckdb", ORIGEM)
        errado = montar(base, "errado.duckdb", DESTINO_ERRADO)
        certo = montar(base, "certo.duckdb", DESTINO_CERTO)
        incompleto = montar(base, "incompleto.duckdb", DESTINO_INCOMPLETO)
        perfil = os.path.join(base, "perfil-origem.json")

        print("== perfil da origem ==")
        rc, _, _ = rodar("duckdb", origem, "--saida", perfil)
        checa(rc == 0, "perfilar a origem retorna 0")

        p = json.load(open(perfil, encoding="utf-8"))
        checa(set(p["views"]) == {"vw_resumo", "vw_por_regiao"},
              "descobriu as duas views sozinho")
        cols = p["views"]["vw_resumo"]["colunas"]
        checa(cols["ticket"]["classe"] == "numerico", "ticket e numerico")
        checa(cols["dia"]["classe"] == "temporal", "dia e temporal")
        checa(cols["ativo"]["classe"] == "booleano", "ativo e booleano")
        checa(cols["ticket"]["metricas"]["nao_nulos"] == "3",
              "ticket tem 3 nao-nulos na origem (os 2 qtd=0 viram NULL)")

        print("\n== traducao ERRADA (tem que acusar) ==")
        rc, out, _ = rodar("duckdb", errado, "--saida", os.path.join(base, "e.json"),
                           "--comparar-com", perfil)
        print(out.strip())
        checa(rc == 1, "sai com codigo 1")
        checa("nao_nulos" in out, "acusa que os NULLs viraram zeros")
        checa("minimo" in out or "maximo" in out, "acusa que as datas mudaram")
        checa("vw_por_regiao" not in out, "nao acusa a view que estava certa")

        print("\n== traducao CORRETA (tem que passar) ==")
        rc, out, _ = rodar("duckdb", certo, "--saida", os.path.join(base, "c.json"),
                           "--comparar-com", perfil)
        checa(rc == 0, "sai com codigo 0")
        checa("CONFEREM" in out, "diz que confere")

        print("\n== divergencia estrutural ==")
        rc, out, _ = rodar("duckdb", incompleto, "--saida", os.path.join(base, "i.json"),
                           "--comparar-com", perfil)
        checa(rc == 1, "sai com codigo 1")
        checa("vw_por_regiao" in out and "nao chegou" in out, "acusa a view que sumiu")
        checa("coluna_nova" in out, "acusa a coluna a mais")

        print("\n== modo comparar isolado ==")
        rc, _, _ = rodar("comparar", perfil, os.path.join(base, "e.json"))
        checa(rc == 1, "compara dois perfis ja coletados")

        print("\n== tolerancia ==")
        from conferir_views import _diferem

        checa(not _diferem("soma", "1.0000000001", "1.0", Decimal("1e-6")),
              "ruido de ponto flutuante dentro da tolerancia passa")
        checa(_diferem("soma", "1.1", "1.0", Decimal("1e-9")),
              "diferenca real e acusada")
        checa(_diferem("nao_nulos", "101", "100", Decimal("1")),
              "contagem nao aceita tolerancia")
        checa(_diferem("minimo", "2026-03-05", "2026-05-03", Decimal("1e-9")),
              "datas diferentes sao acusadas")
        checa(not _diferem("minimo", None, None, Decimal("1e-9")),
              "NULL dos dois lados confere")
        checa(_diferem("minimo", None, "0", Decimal("1e-9")),
              "NULL contra valor e acusado")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n" + ("TODOS OS TESTES PASSARAM" if not falhas
                  else f"{len(falhas)} FALHA(S)"))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
