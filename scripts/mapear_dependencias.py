#!/usr/bin/env python3
"""Mapeia quem consome e quem alimenta o datalake, a partir do historico de jobs.

SOMENTE LEITURA. Usa apenas SELECT sobre INFORMATION_SCHEMA.

Por que isso existe: o inventario tecnico descreve o datalake parado — quantas
tabelas, quantos bytes. Nao diz quem depende dele. Duas service accounts com
chave ativa (`datalake-automacao`, `portal-relatorios`) apareceram por acaso,
e cada uma indica um sistema que quebra quando o projeto for excluido. Copiar
todos os bytes e ainda assim derrubar um sistema em producao nao e uma
migracao bem-sucedida.

O historico de jobs do BigQuery guarda 180 dias e responde, com evidencia:

- **Quem consulta o datalake** — todos os principais, nao so os dois conhecidos
- **Se o portal consulta o BigQuery direto** — se aparecer rodando jobs, sim, e
  precisa ser reapontado para o DuckDB antes da desativacao
- **Que tabelas cada um le** — o que exatamente quebra, e o que o portal precisa
  que exista no destino
- **Quando o bronze e escrito** — a janela em que exportar produz copia
  desatualizada, e o que precisa ser congelado na fase 5
- **Quanta traducao de dialeto falta** — as consultas dos consumidores tem o
  mesmo problema das 11 views do `gold`

O que ele *nao* responde: onde cada sistema roda. Isso o historico de jobs nao
registra; e preciso rastrear onde a chave de cada service account foi instalada.

Uso:
  python scripts/mapear_dependencias.py --projeto tterrasul-datalake
  python scripts/mapear_dependencias.py --dias 30 --incluir-sql
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from carregar_duckdb import CONSTRUCOES_DIVERGENTES
from gcp_credenciais import (
    ESCOPO_BIGQUERY,
    PROJECT_ENV,
    SetupError,
    obter_credenciais,
)

# A regiao entra no nome da tabela e nao pode ser parametrizada pela API, entao
# e interpolada. Validar aqui e o que impede que o valor vire injecao de SQL.
REGIAO_VALIDA = re.compile(r"^[a-z0-9-]+$")

# INFORMATION_SCHEMA guarda 180 dias de historico; pedir mais nao traz nada.
DIAS_MAX = 180


def _tabela_jobs(regiao: str) -> str:
    return f"`region-{regiao}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT"


def consultar(client, sql: str, dias: int, **extras):
    """Roda uma query com o recorte de dias e devolve as linhas como dicts."""
    from google.cloud import bigquery

    params = [bigquery.ScalarQueryParameter("dias", "INT64", dias)]
    params += [
        bigquery.ScalarQueryParameter(nome, "INT64", valor)
        for nome, valor in extras.items()
    ]
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(linha) for linha in client.query(sql, job_config=cfg).result()]


# --- Consultas ---------------------------------------------------------------
# Cada uma responde a uma das perguntas em aberto do documento de migracao.


def principais(client, regiao: str, dias: int):
    """Quem tocou o projeto, com que tipo de job, e quando pela ultima vez."""
    sql = f"""
    SELECT
      user_email,
      job_type,
      COUNT(*) AS jobs,
      COUNTIF(error_result IS NOT NULL) AS jobs_com_erro,
      MIN(creation_time) AS primeiro,
      MAX(creation_time) AS ultimo,
      IFNULL(SUM(total_bytes_processed), 0) AS bytes_processados
    FROM {_tabela_jobs(regiao)}
    WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @dias DAY)
    GROUP BY user_email, job_type
    ORDER BY jobs DESC
    """
    return consultar(client, sql, dias)


def leituras(client, regiao: str, dias: int):
    """Que tabelas cada principal leu — isto e, o que quebra na desativacao.

    referenced_tables cobre as tabelas de entrada do job; a de destino sai na
    consulta de escritas.
    """
    sql = f"""
    SELECT
      user_email,
      ref.dataset_id AS dataset_id,
      ref.table_id AS table_id,
      COUNT(*) AS jobs,
      MAX(creation_time) AS ultimo
    FROM {_tabela_jobs(regiao)}, UNNEST(referenced_tables) AS ref
    WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @dias DAY)
      AND ref.dataset_id != 'INFORMATION_SCHEMA'
    GROUP BY user_email, dataset_id, table_id
    ORDER BY jobs DESC
    """
    return consultar(client, sql, dias)


def escritas(client, regiao: str, dias: int):
    """Quem escreve, em que dataset e com que frequencia.

    E a lista do que precisa parar na fase 5: enquanto qualquer uma dessas
    linhas continuar avancando, o alvo nao esta estatico e a verificacao da
    fase 4 nao vale.
    """
    sql = f"""
    SELECT
      user_email,
      statement_type,
      destination_table.dataset_id AS dataset_id,
      COUNT(DISTINCT destination_table.table_id) AS tabelas,
      COUNT(*) AS jobs,
      MAX(creation_time) AS ultimo
    FROM {_tabela_jobs(regiao)}
    WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @dias DAY)
      AND destination_table IS NOT NULL
      AND destination_table.dataset_id NOT LIKE '_%'
    GROUP BY user_email, statement_type, dataset_id
    ORDER BY jobs DESC
    """
    return consultar(client, sql, dias)


def horario_das_escritas(client, regiao: str, dias: int):
    """Distribuicao horaria das escritas — define a janela segura de exportacao."""
    sql = f"""
    SELECT
      EXTRACT(HOUR FROM creation_time AT TIME ZONE 'America/Sao_Paulo') AS hora,
      COUNT(*) AS jobs
    FROM {_tabela_jobs(regiao)}
    WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @dias DAY)
      AND destination_table IS NOT NULL
      AND destination_table.dataset_id NOT LIKE '_%'
    GROUP BY hora
    ORDER BY hora
    """
    return consultar(client, sql, dias)


def consultas_dos_consumidores(client, regiao: str, dias: int, limite: int):
    """As consultas distintas que rodam contra o datalake.

    Agrupar pelo texto exato deduplica execucoes repetidas da mesma consulta,
    que e o padrao de uma aplicacao. Consultas ao proprio INFORMATION_SCHEMA
    ficam de fora: sao os scripts desta migracao se enxergando.
    """
    sql = f"""
    SELECT
      user_email,
      query,
      COUNT(*) AS execucoes,
      MAX(creation_time) AS ultimo
    FROM {_tabela_jobs(regiao)}
    WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @dias DAY)
      AND job_type = 'QUERY'
      AND query IS NOT NULL
      AND NOT CONTAINS_SUBSTR(UPPER(query), 'INFORMATION_SCHEMA')
    GROUP BY user_email, query
    ORDER BY execucoes DESC
    LIMIT @limite
    """
    return consultar(client, sql, dias, limite=limite)


def dialeto(sql: str) -> list[str]:
    """Construcoes do SQL que nao sobrevivem a mudanca para o DuckDB."""
    alto = sql.upper()
    return [nota for termo, nota in CONSTRUCOES_DIVERGENTES if termo in alto]


# --- Relatorio ---------------------------------------------------------------


def _tabela_md(cabecalho: list[str], linhas: list[list], vazio: str) -> list[str]:
    if not linhas:
        return [f"_{vazio}_", ""]
    out = ["| " + " | ".join(cabecalho) + " |",
           "| " + " | ".join("---" for _ in cabecalho) + " |"]
    out += ["| " + " | ".join(str(c) for c in linha) + " |" for linha in linhas]
    out.append("")
    return out


def _dia(valor) -> str:
    """Data de um timestamp, ou vazio. So a data: a hora nao muda decisao aqui."""
    return str(valor)[:10] if valor else ""


def montar_relatorio(dados: dict, projeto: str, dias: int) -> str:
    ln: list[str] = [
        f"# Dependencias vivas — `{projeto}`",
        "",
        f"Gerado em {datetime.now(timezone.utc).isoformat()} · "
        f"janela de {dias} dias · somente leitura",
        "",
        "## Quem tocou o projeto",
        "",
    ]

    ln += _tabela_md(
        ["Principal", "Tipo", "Jobs", "Com erro", "Primeiro", "Ultimo"],
        [
            [r["user_email"], r["job_type"], f'{r["jobs"]:,}', r["jobs_com_erro"],
             _dia(r["primeiro"]), _dia(r["ultimo"])]
            for r in dados["principais"]
        ],
        "Nenhum job na janela. Ou o projeto esta ocioso, ou a janela e curta demais.",
    )

    # A pergunta em aberto do documento: o portal consulta o BigQuery direto?
    #
    # Quem consulta e quem escreve pedem acoes opostas, entao os dois grupos
    # nao podem sair na mesma lista: um consumidor puro precisa ser reapontado
    # para o DuckDB e continuar rodando; quem alimenta o bronze precisa e
    # *parar*, e reapontar seria o erro.
    escritores = {r["user_email"] for r in dados["escritas"]}
    consultantes = {
        r["user_email"] for r in dados["principais"] if r["job_type"] == "QUERY"
    }
    so_leem = sorted(consultantes - escritores)
    leem_e_escrevem = sorted(consultantes & escritores)

    ln += ["## O portal consulta o BigQuery direto?", ""]
    if not consultantes:
        ln += ["Nenhum job de consulta na janela.", ""]
    else:
        if so_leem:
            ln += [
                "**Consomem e nao escrevem.** Leem o BigQuery diretamente e param",
                "de funcionar quando o projeto for excluido. Cada um precisa ser",
                "reapontado para o DuckDB antes da fase 6:",
                "",
            ]
            ln += [f"- `{e}`" for e in so_leem]
            ln.append("")
        if leem_e_escrevem:
            ln += [
                "**Consultam e tambem escrevem.** Sao parte do pipeline, nao",
                "consumidores finais: o destino deles e parar na fase 5, nao ser",
                "reapontado. Confira na tabela de escritas antes de decidir:",
                "",
            ]
            ln += [f"- `{e}`" for e in leem_e_escrevem]
            ln.append("")

    ln += ["## O que cada um le", "",
           "O que exatamente quebra na desativacao, e o que precisa existir no",
           "DuckDB para o consumidor continuar de pe.", ""]

    por_principal: dict[str, dict] = {}
    for r in dados["leituras"]:
        acc = por_principal.setdefault(
            r["user_email"], {"datasets": set(), "tabelas": 0, "jobs": 0, "ultimo": None}
        )
        acc["datasets"].add(r["dataset_id"])
        acc["tabelas"] += 1
        acc["jobs"] += r["jobs"]
        acc["ultimo"] = max(acc["ultimo"] or r["ultimo"], r["ultimo"])

    ln += _tabela_md(
        ["Principal", "Datasets", "Tabelas distintas", "Jobs", "Ultimo"],
        [
            [email, ", ".join(sorted(v["datasets"])) or "—", v["tabelas"],
             f'{v["jobs"]:,}', _dia(v["ultimo"])]
            for email, v in sorted(por_principal.items(),
                                   key=lambda kv: -kv[1]["jobs"])
        ],
        "Nenhuma leitura registrada.",
    )

    ln += ["## Quem escreve — congelar na fase 5", "",
           "Enquanto qualquer uma destas linhas continuar avancando, o alvo nao",
           "esta estatico e a verificacao da fase 4 nao vale.", ""]

    ln += _tabela_md(
        ["Principal", "Operacao", "Dataset", "Tabelas", "Jobs", "Ultimo"],
        [
            [r["user_email"], r["statement_type"] or "LOAD", r["dataset_id"],
             r["tabelas"], f'{r["jobs"]:,}', _dia(r["ultimo"])]
            for r in dados["escritas"]
        ],
        "Nenhuma escrita registrada — o bronze pode estar sendo alimentado por "
        "fora do BigQuery, ou a automacao ja parou.",
    )

    horas = dados["horario_das_escritas"]
    ln += ["## Janela segura para exportar", ""]
    if horas:
        pico = max(horas, key=lambda r: r["jobs"])
        ociosas = sorted(set(range(24)) - {r["hora"] for r in horas})
        ln += [
            "Escritas por hora (America/Sao_Paulo). Exportar durante um pico "
            "produz copia que ja nasce desatualizada.",
            "",
        ]
        ln += _tabela_md(
            ["Hora", "Jobs de escrita"],
            [[f'{r["hora"]:02d}h', f'{r["jobs"]:,}'] for r in horas],
            "",
        )
        ln += [
            f'Pico as {pico["hora"]:02d}h ({pico["jobs"]:,} jobs).',
            "",
            ("Horas sem nenhuma escrita na janela: "
             + ", ".join(f"{h:02d}h" for h in ociosas) + "."
             if ociosas else
             "Nao houve nenhuma hora do dia sem escrita — nao existe janela "
             "ociosa natural, e a exportacao exige parar a automacao antes."),
            "",
        ]
    else:
        ln += ["_Sem escritas registradas; nao ha janela a evitar._", ""]

    ln += ["## Traducao de dialeto pendente", "",
           "As consultas dos consumidores sao SQL do BigQuery e tem o mesmo",
           "problema das 11 views do `gold`: nao rodam como estao no DuckDB.", ""]

    achados = dados["dialeto_por_principal"]
    ln += _tabela_md(
        ["Principal", "Consultas distintas", "Com construcao divergente"],
        [
            [email, v["consultas"], v["divergentes"]]
            for email, v in sorted(achados.items(), key=lambda kv: -kv[1]["divergentes"])
        ],
        "Nenhuma consulta de aplicacao na janela.",
    )

    if dados["construcoes"]:
        ln += ["Construcoes encontradas, por frequencia:", ""]
        ln += [f'- {nota} — {n} consulta(s)'
               for nota, n in sorted(dados["construcoes"].items(),
                                     key=lambda kv: -kv[1])]
        ln.append("")

    ln += [
        "## O que isto nao responde",
        "",
        "**Onde cada sistema roda.** O historico de jobs registra a identidade,",
        "nao a maquina. Para cada principal acima, rastreie onde a chave da",
        "service account foi instalada antes de desativar o faturamento.",
        "",
        "**Consumidores que nao passam pelo BigQuery.** Quem le o bucket direto",
        "por HTTP, ou algum export ja materializado, nao aparece aqui.",
        "",
    ]
    return "\n".join(ln)


# --- Principal ---------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--projeto", default=os.environ.get(PROJECT_ENV),
                   help=f"ID do projeto (padrao: ${PROJECT_ENV} ou o da credencial)")
    p.add_argument("--regiao", default="southamerica-east1",
                   help="regiao dos datasets (padrao: southamerica-east1)")
    p.add_argument("--dias", type=int, default=DIAS_MAX,
                   help=f"janela do historico, ate {DIAS_MAX} (padrao: {DIAS_MAX})")
    p.add_argument("--limite-consultas", type=int, default=2000,
                   help="maximo de consultas distintas inspecionadas (padrao: 2000)")
    p.add_argument("--saida", default=None, help="pasta de saida (padrao: dependencias-<data>)")
    p.add_argument("--incluir-sql", action="store_true",
                   help="salva tambem o texto das consultas (logica de negocio; "
                        "nao versione)")
    args = p.parse_args()

    if not REGIAO_VALIDA.match(args.regiao):
        print(f"erro: regiao invalida: {args.regiao!r}", file=sys.stderr)
        return 2
    if not 1 <= args.dias <= DIAS_MAX:
        print(f"erro: --dias deve estar entre 1 e {DIAS_MAX} "
              "(o historico do BigQuery nao guarda mais que isso)", file=sys.stderr)
        return 2

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
    print(f"projeto: {projeto}", file=sys.stderr)
    print(f"identidade: {identidade}", file=sys.stderr)
    print(f"janela: {args.dias} dias · regiao: {args.regiao}\n", file=sys.stderr)

    dados: dict = {}
    etapas = [
        ("principais", principais),
        ("leituras", leituras),
        ("escritas", escritas),
        ("horario_das_escritas", horario_das_escritas),
    ]
    try:
        for nome, fn in etapas:
            print(f"  consultando {nome}...", file=sys.stderr)
            dados[nome] = fn(client, args.regiao, args.dias)

        print("  consultando consultas_dos_consumidores...", file=sys.stderr)
        consultas = consultas_dos_consumidores(
            client, args.regiao, args.dias, args.limite_consultas
        )
    except Exception as exc:
        print(f"\nerro ao consultar o historico de jobs: {exc}", file=sys.stderr)
        msg = str(exc).lower()
        if "403" in msg or "permission" in msg or "denied" in msg:
            print(
                "\nA credencial autenticou mas nao pode ler o historico de jobs "
                "do projeto.\nJOBS_BY_PROJECT exige `bigquery.jobs.listAll`, que "
                "a leitura de dados\nnao inclui. Conceda o papel — que continua "
                "somente leitura:\n\n"
                f"  gcloud projects add-iam-policy-binding {projeto} \\\n"
                f'    --member="serviceAccount:{identidade}" \\\n'
                '    --role="roles/bigquery.resourceViewer"\n\n'
                "Sem isso o script so enxergaria os proprios jobs, que nao "
                "respondem nada.",
                file=sys.stderr,
            )
        elif "not found" in msg or "404" in msg:
            print(
                f"\nRegiao {args.regiao!r} pode estar errada: INFORMATION_SCHEMA "
                "e por regiao,\ne consultar a regiao errada devolve 'not found' "
                "mesmo com acesso.",
                file=sys.stderr,
            )
        return 1

    # Varredura de dialeto do lado do cliente: evita trafegar o texto das
    # consultas mais de uma vez e reusa a lista que ja governa as views.
    por_principal: dict[str, dict] = {}
    construcoes: dict[str, int] = {}
    for r in consultas:
        acc = por_principal.setdefault(r["user_email"], {"consultas": 0, "divergentes": 0})
        acc["consultas"] += 1
        notas = dialeto(r["query"])
        if notas:
            acc["divergentes"] += 1
        for nota in notas:
            construcoes[nota] = construcoes.get(nota, 0) + 1

    dados["dialeto_por_principal"] = por_principal
    dados["construcoes"] = construcoes

    saida = args.saida or f"dependencias-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(saida, exist_ok=True)

    relatorio = montar_relatorio(dados, projeto, args.dias)
    with open(os.path.join(saida, "relatorio.md"), "w", encoding="utf-8") as fh:
        fh.write(relatorio)

    with open(os.path.join(saida, "dados.json"), "w", encoding="utf-8") as fh:
        json.dump(dados, fh, indent=2, ensure_ascii=False, default=str)

    if args.incluir_sql:
        pasta = os.path.join(saida, "consultas")
        os.makedirs(pasta, exist_ok=True)
        for i, r in enumerate(consultas, 1):
            with open(os.path.join(pasta, f"{i:04d}.sql"), "w", encoding="utf-8") as fh:
                fh.write(f"-- {r['user_email']} · {r['execucoes']} execucoes\n"
                         f"-- ultimo: {r['ultimo']}\n\n{r['query']}\n")

    print(relatorio)
    print(f"\nrelatorio salvo em {saida}/", file=sys.stderr)
    if args.incluir_sql:
        print(
            f"\nAVISO: {saida}/consultas/ contem o SQL das aplicacoes, que e "
            "logica de negocio.\nNao versione neste repositorio — "
            "`Fersouro/Fersouro` e o perfil publico do GitHub.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
