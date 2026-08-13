#!/usr/bin/env python3
"""Confere se as views traduzidas devolvem o mesmo que devolviam no BigQuery.

SOMENTE LEITURA nos dois lados.

A fase 4, como estava, conferia as views checando se os arquivos `.sql`
existem e nao estao vazios. Isso prova que o arquivo foi baixado, nao que a
traducao esta certa. E a traducao e justamente o passo onde o erro nao
aparece: `SAFE_DIVIDE` virando divisao comum troca um NULL por um erro — ou
pior, por um zero; `PARSE_DATE` com formato trocado desloca datas em silencio.
O resultado continua com cara de certo.

Este script compara o **conteudo** dos dois lados. Para cada view ele calcula
um perfil — contagem de linhas e, por coluna, nao-nulos, distintos, minimo,
maximo e soma — e depois confronta perfil com perfil. Nao e igualdade linha a
linha, e nao promete ser: e o conjunto de agregados que muda quando a
semantica muda, que e o que se quer pegar.

**Colete o perfil do BigQuery antes da fase 5.** Depois da exclusao do
projeto nao existe mais contra o que comparar — o perfil e tao irreproduzivel
quanto as proprias views, e pela mesma razao.

Uso:
  python scripts/conferir_views.py bigquery --dataset gold --saida perfil-bq.json
  python scripts/conferir_views.py duckdb D:/datalake/datalake.duckdb --saida perfil-duck.json
  python scripts/conferir_views.py comparar perfil-bq.json perfil-duck.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from decimal import Decimal, InvalidOperation

from gcp_credenciais import ESCOPO_BIGQUERY, PROJECT_ENV, SetupError, obter_credenciais

# Metricas por classe de tipo. Nem toda metrica faz sentido em toda coluna:
# somar texto nao significa nada, e ARRAY/STRUCT nem ordenam, entao desses so
# da para contar o que nao e nulo.
METRICAS = {
    "numerico": ["nao_nulos", "distintos", "minimo", "maximo", "soma"],
    "temporal": ["nao_nulos", "distintos", "minimo", "maximo"],
    "texto": ["nao_nulos", "distintos", "minimo", "maximo"],
    "booleano": ["nao_nulos", "verdadeiros"],
    "opaco": ["nao_nulos"],
}

# Contagens tem que bater exatamente; agregados numericos admitem tolerancia
# porque ponto flutuante nao sobrevive intacto a uma troca de motor.
METRICAS_EXATAS = {"linhas", "nao_nulos", "distintos", "verdadeiros"}

TOLERANCIA_PADRAO = Decimal("1e-9")


# --- Normalizacao de valores -------------------------------------------------


def _normalizar(valor):
    """Converte um valor de agregado para algo comparavel e serializavel."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return str(valor).lower()
    if isinstance(valor, (int, Decimal)):
        return str(valor)
    if isinstance(valor, float):
        return repr(valor)
    if isinstance(valor, (_dt.datetime, _dt.date, _dt.time)):
        return valor.isoformat()
    if isinstance(valor, bytes):
        return valor.hex()
    return str(valor)


# --- Perfiladores ------------------------------------------------------------


class Perfilador:
    """Interface comum aos dois motores.

    O SQL dos agregados e quase todo identico entre BigQuery e DuckDB; o que
    diverge — aspas do identificador e como se conta um booleano — fica nas
    subclasses, para que a montagem da consulta exista uma vez so.
    """

    nome = "?"

    def citar(self, ident: str) -> str:
        raise NotImplementedError

    def contar_verdadeiros(self, col: str) -> str:
        raise NotImplementedError

    def listar_views(self) -> list[str]:
        raise NotImplementedError

    def colunas(self, view: str) -> list[tuple[str, str]]:
        """Devolve [(nome, classe)] na ordem da view."""
        raise NotImplementedError

    def executar(self, sql: str) -> tuple:
        raise NotImplementedError

    def alvo(self, view: str) -> str:
        raise NotImplementedError

    def montar_consulta(self, view: str, colunas: list[tuple[str, str]]) -> tuple[str, list]:
        """Monta uma unica consulta com todos os agregados da view.

        Os apelidos sao posicionais (`c0__soma`) de proposito: nome de coluna
        pode ter acento, espaco ou maiuscula, e cada motor normaliza isso de um
        jeito. A posicao nao muda.
        """
        selecoes = ["COUNT(*) AS linhas"]
        plano: list[tuple[int, str, str]] = []

        for i, (nome, classe) in enumerate(colunas):
            q = self.citar(nome)
            for metrica in METRICAS[classe]:
                expr = {
                    "nao_nulos": f"COUNT({q})",
                    "distintos": f"COUNT(DISTINCT {q})",
                    "minimo": f"MIN({q})",
                    "maximo": f"MAX({q})",
                    "soma": f"SUM({q})",
                    "verdadeiros": self.contar_verdadeiros(q),
                }[metrica]
                selecoes.append(f"{expr} AS c{i}__{metrica}")
                plano.append((i, nome, metrica))

        sql = "SELECT " + ", ".join(selecoes) + f" FROM {self.alvo(view)}"
        return sql, plano

    def perfilar(self, view: str) -> dict:
        colunas = self.colunas(view)
        sql, plano = self.montar_consulta(view, colunas)
        linha = self.executar(sql)

        perfil = {
            "linhas": int(linha[0]),
            "colunas": {
                nome: {"classe": classe, "metricas": {}}
                for nome, classe in colunas
            },
        }
        for pos, (_, nome, metrica) in enumerate(plano, start=1):
            perfil["colunas"][nome]["metricas"][metrica] = _normalizar(linha[pos])
        return perfil


class PerfiladorBigQuery(Perfilador):
    nome = "bigquery"

    NUMERICO = {"INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC",
                "DECIMAL", "BIGDECIMAL"}
    TEMPORAL = {"DATE", "DATETIME", "TIME", "TIMESTAMP"}

    def __init__(self, client, projeto: str, dataset: str):
        self.client = client
        self.projeto = projeto
        self.dataset = dataset

    def citar(self, ident: str) -> str:
        return "`" + ident.replace("`", "\\`") + "`"

    def contar_verdadeiros(self, col: str) -> str:
        return f"COUNTIF({col})"

    def alvo(self, view: str) -> str:
        return f"`{self.projeto}.{self.dataset}.{view}`"

    def listar_views(self) -> list[str]:
        sql = (f"SELECT table_name FROM `{self.projeto}.{self.dataset}"
               ".INFORMATION_SCHEMA.TABLES` WHERE table_type = 'VIEW' "
               "ORDER BY table_name")
        return [r[0] for r in self.client.query(sql).result()]

    def colunas(self, view: str) -> list[tuple[str, str]]:
        tabela = self.client.get_table(f"{self.projeto}.{self.dataset}.{view}")
        out = []
        for campo in tabela.schema:
            tipo = (campo.field_type or "").upper()
            if campo.mode == "REPEATED" or tipo in ("RECORD", "STRUCT"):
                classe = "opaco"
            elif tipo in self.NUMERICO:
                classe = "numerico"
            elif tipo in self.TEMPORAL:
                classe = "temporal"
            elif tipo == "STRING":
                classe = "texto"
            elif tipo in ("BOOLEAN", "BOOL"):
                classe = "booleano"
            else:
                classe = "opaco"
            out.append((campo.name, classe))
        return out

    def executar(self, sql: str) -> tuple:
        return list(self.client.query(sql).result())[0]

    def estimar(self, sql: str) -> int:
        """Bytes que a consulta leria, sem executar nem cobrar."""
        from google.cloud import bigquery

        cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        return self.client.query(sql, job_config=cfg).total_bytes_processed or 0


class PerfiladorDuckDB(Perfilador):
    nome = "duckdb"

    def __init__(self, con, schema: str):
        self.con = con
        self.schema = schema

    def citar(self, ident: str) -> str:
        return '"' + ident.replace('"', '""') + '"'

    def contar_verdadeiros(self, col: str) -> str:
        return f"COUNT(*) FILTER (WHERE {col})"

    def alvo(self, view: str) -> str:
        return f"{self.citar(self.schema)}.{self.citar(view)}"

    def listar_views(self) -> list[str]:
        return [r[0] for r in self.con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = ? AND table_type = 'VIEW' ORDER BY table_name",
            [self.schema],
        ).fetchall()]

    def colunas(self, view: str) -> list[tuple[str, str]]:
        out = []
        for linha in self.con.execute(f"DESCRIBE {self.alvo(view)}").fetchall():
            nome, tipo = linha[0], (linha[1] or "").upper()
            out.append((nome, self._classificar(tipo)))
        return out

    @staticmethod
    def _classificar(tipo: str) -> str:
        # Compostos primeiro: DECIMAL(18,3)[] e um array, nao um numero.
        if "[]" in tipo or tipo.startswith(("STRUCT", "MAP", "UNION", "LIST")):
            return "opaco"
        if tipo == "BOOLEAN":
            return "booleano"
        if tipo.startswith(("DECIMAL", "NUMERIC")) or tipo in {
            "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
            "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
            "FLOAT", "DOUBLE", "REAL",
        }:
            return "numerico"
        if tipo.startswith("TIMESTAMP") or tipo in {"DATE", "TIME", "TIMETZ"}:
            return "temporal"
        if tipo.startswith(("VARCHAR", "CHAR")) or tipo in {"TEXT", "STRING", "UUID"}:
            return "texto"
        return "opaco"

    def executar(self, sql: str) -> tuple:
        return self.con.execute(sql).fetchone()


def perfilar_tudo(perfilador: Perfilador, views: list[str] | None) -> dict:
    alvos = views or perfilador.listar_views()
    perfis: dict = {}
    for view in alvos:
        print(f"  {view}...", file=sys.stderr, flush=True)
        try:
            perfis[view] = perfilador.perfilar(view)
        except Exception as exc:
            print(f"    FALHOU: {exc}", file=sys.stderr)
            perfis[view] = {"erro": str(exc)}
    return {"motor": perfilador.nome, "views": perfis}


# --- Comparacao --------------------------------------------------------------


def _como_decimal(valor):
    if valor is None:
        return None
    try:
        d = Decimal(valor)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


def _diferem(metrica: str, a, b, tolerancia: Decimal) -> bool:
    if a is None or b is None:
        return a != b
    if a == b:
        return False
    if metrica in METRICAS_EXATAS:
        return True

    da, db = _como_decimal(a), _como_decimal(b)
    if da is None or db is None:
        return True  # Texto ou data: sem tolerancia possivel, e ja sao diferentes.

    escala = max(abs(da), abs(db))
    return abs(da - db) > (tolerancia * escala if escala else tolerancia)


def comparar(origem: dict, destino: dict, tolerancia: Decimal) -> list[str]:
    """Confronta dois perfis e devolve a lista de divergencias."""
    divergencias: list[str] = []
    vo, vd = origem["views"], destino["views"]

    for nome in sorted(set(vo) - set(vd)):
        divergencias.append(f"{nome}: existe na origem e nao chegou ao destino")
    for nome in sorted(set(vd) - set(vo)):
        divergencias.append(f"{nome}: existe no destino e nao na origem")

    for nome in sorted(set(vo) & set(vd)):
        a, b = vo[nome], vd[nome]
        for lado, perfil in (("origem", a), ("destino", b)):
            if "erro" in perfil:
                divergencias.append(f"{nome}: falhou ao perfilar na {lado} — {perfil['erro']}")
        if "erro" in a or "erro" in b:
            continue

        if a["linhas"] != b["linhas"]:
            divergencias.append(
                f"{nome}: {a['linhas']:,} linhas na origem, {b['linhas']:,} no destino"
            )

        ca, cb = a["colunas"], b["colunas"]
        for col in sorted(set(ca) - set(cb)):
            divergencias.append(f"{nome}.{col}: coluna sumiu na traducao")
        for col in sorted(set(cb) - set(ca)):
            divergencias.append(f"{nome}.{col}: coluna a mais no destino")

        for col in sorted(set(ca) & set(cb)):
            if ca[col]["classe"] != cb[col]["classe"]:
                divergencias.append(
                    f"{nome}.{col}: tipo mudou — {ca[col]['classe']} na origem, "
                    f"{cb[col]['classe']} no destino"
                )
                continue
            ma, mb = ca[col]["metricas"], cb[col]["metricas"]
            for metrica in sorted(set(ma) & set(mb)):
                if _diferem(metrica, ma[metrica], mb[metrica], tolerancia):
                    divergencias.append(
                        f"{nome}.{col}: {metrica} — origem {ma[metrica]}, "
                        f"destino {mb[metrica]}"
                    )

    return divergencias


def relatar(origem: dict, destino: dict, divergencias: list[str]) -> None:
    n = len(set(origem["views"]) & set(destino["views"]))
    print(f"views comparadas: {n}")
    if not divergencias:
        print("\nCONFEREM: os perfis batem em todas as views.")
        print("As traducoes preservam contagem, dominio e totais de cada coluna.")
        return

    print(f"\nDIVERGENCIAS ({len(divergencias)}):")
    for d in divergencias[:60]:
        print(f"  - {d}")
    if len(divergencias) > 60:
        print(f"  ... e mais {len(divergencias) - 60}")
    print("\nCada linha acima e um ponto em que o destino responde diferente da")
    print("origem. NAO prossiga para a desativacao do projeto.")


# --- CLI ---------------------------------------------------------------------


def _salvar(perfil: dict, caminho: str) -> None:
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(perfil, fh, indent=2, ensure_ascii=False)
    print(f"perfil salvo em {caminho}", file=sys.stderr)


def _carregar(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--tolerancia", type=Decimal, default=TOLERANCIA_PADRAO,
                   help="tolerancia relativa nos agregados numericos "
                        f"(padrao: {TOLERANCIA_PADRAO})")
    sub = p.add_subparsers(dest="modo", required=True)

    bq = sub.add_parser("bigquery", help="perfila as views na origem (BigQuery)")
    bq.add_argument("--projeto", default=os.environ.get(PROJECT_ENV))
    bq.add_argument("--dataset", default="gold")
    bq.add_argument("--views", nargs="*", default=None,
                    help="views especificas (padrao: todas as views do dataset)")
    bq.add_argument("--saida", default="perfil-bigquery.json")
    bq.add_argument("--estimar", action="store_true",
                    help="so estima os bytes lidos, sem executar nem cobrar")

    dk = sub.add_parser("duckdb", help="perfila as views no destino (DuckDB)")
    dk.add_argument("banco", help="arquivo .duckdb")
    dk.add_argument("--schema", default="gold")
    dk.add_argument("--views", nargs="*", default=None)
    dk.add_argument("--saida", default="perfil-duckdb.json")
    dk.add_argument("--comparar-com", default=None,
                    help="perfil da origem; compara logo apos perfilar")

    cmp_ = sub.add_parser("comparar", help="confronta dois perfis ja coletados")
    cmp_.add_argument("origem")
    cmp_.add_argument("destino")

    args = p.parse_args()

    if args.modo == "comparar":
        origem, destino = _carregar(args.origem), _carregar(args.destino)
        divergencias = comparar(origem, destino, args.tolerancia)
        relatar(origem, destino, divergencias)
        return 1 if divergencias else 0

    if args.modo == "bigquery":
        try:
            from google.cloud import bigquery
        except ImportError:
            print("erro: google-cloud-bigquery nao instalado. Rode:\n"
                  "  pip install -r requirements.txt", file=sys.stderr)
            return 2
        try:
            credentials, projeto, identidade = obter_credenciais(
                [ESCOPO_BIGQUERY], args.projeto
            )
        except SetupError as exc:
            print(f"erro de configuracao: {exc}", file=sys.stderr)
            return 2

        client = bigquery.Client(project=projeto, credentials=credentials)
        perfilador = PerfiladorBigQuery(client, projeto, args.dataset)
        print(f"projeto: {projeto} · dataset: {args.dataset}", file=sys.stderr)
        print(f"identidade: {identidade}\n", file=sys.stderr)

        try:
            alvos = args.views or perfilador.listar_views()
        except Exception as exc:
            print(f"erro ao listar views: {exc}", file=sys.stderr)
            return 1

        if not alvos:
            print(f"nenhuma view em {args.dataset}.", file=sys.stderr)
            return 1

        if args.estimar:
            total = 0
            for view in alvos:
                sql, _ = perfilador.montar_consulta(view, perfilador.colunas(view))
                bytes_ = perfilador.estimar(sql)
                total += bytes_
                print(f"  {view}: {bytes_ / 2**30:.2f} GiB")
            print(f"\ntotal estimado: {total / 2**30:.2f} GiB lidos")
            print("Nada foi executado nem cobrado.")
            return 0

        _salvar(perfilar_tudo(perfilador, alvos), args.saida)
        print("\nGuarde este arquivo fora do projeto GCP: depois da fase 6 ele e a\n"
              "unica referencia do que as views respondiam.", file=sys.stderr)
        return 0

    # duckdb
    try:
        import duckdb
    except ImportError:
        print("erro: duckdb nao instalado. Rode: pip install duckdb", file=sys.stderr)
        return 2

    if not os.path.exists(args.banco):
        print(f"erro: {args.banco} nao existe", file=sys.stderr)
        return 2

    con = duckdb.connect(args.banco, read_only=True)
    perfilador = PerfiladorDuckDB(con, args.schema)
    alvos = args.views or perfilador.listar_views()
    if not alvos:
        print(f"nenhuma view no schema {args.schema}. As views ja foram criadas?",
              file=sys.stderr)
        return 1

    destino = perfilar_tudo(perfilador, alvos)
    con.close()
    _salvar(destino, args.saida)

    if args.comparar_com:
        origem = _carregar(args.comparar_com)
        divergencias = comparar(origem, destino, args.tolerancia)
        print()
        relatar(origem, destino, divergencias)
        return 1 if divergencias else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
