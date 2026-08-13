"""Interface de linha de comando do datalake.

    datalake init                      cria a estrutura de diretorios e o controle
    datalake sources                   lista fontes e tabelas configuradas
    datalake test-connection           testa a conexao com a origem
    datalake discover                  le o dicionario de dados e propõe o YAML
    datalake peek                      espia as primeiras linhas da origem
    datalake sql "SELECT ..."          consulta de leitura na origem
    datalake ingest                    origem  -> bronze
    datalake silver                    bronze  -> silver
    datalake gold                      silver  -> gold
    datalake quality                   testes de qualidade sobre a silver
    datalake catalog                   atualiza data/lake.duckdb
    datalake run                       pipeline completo
    datalake state                     watermarks e ultimas execucoes
    datalake query "SELECT ..."        consulta rapida no lake
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import ConfigError, Settings, load_settings
from .connectors.base import ConnectorError
from .logging_conf import get_logger, setup_logging
from .state.control import ControlDB, new_run_id

log = get_logger("datalake.cli")

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2


# --------------------------------------------------------------------- helpers
def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Tabela de texto simples, sem dependencia externa."""
    if not rows:
        return "(nenhum registro)"
    data = [[("" if c is None else str(c)) for c in row] for row in rows]
    widths = [
        max(len(str(headers[i])), max((len(r[i]) for r in data), default=0))
        for i in range(len(headers))
    ]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths)).rstrip()
    separator = "  ".join("-" * w for w in widths)
    body = "\n".join(
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in data
    )
    return f"{line}\n{separator}\n{body}"


def _selected_sources(settings: Settings, name: str | None):
    return [settings.source(name)] if name else list(settings.sources)


def _summary(results) -> tuple[int, int]:
    ok = sum(1 for r in results if r.ok)
    return ok, len(results) - ok


# -------------------------------------------------------------------- comandos
def cmd_init(args, settings: Settings) -> int:
    from .storage.paths import ensure_layout

    created = ensure_layout(settings.root)
    ControlDB(settings.control_db)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    print(f"Raiz do lake: {settings.root}")
    for path in created:
        print(f"  criado: {path}")
    print(f"Banco de controle: {settings.control_db}")
    print(f"Fontes configuradas: {len(settings.sources)}")
    env = settings.project_root / ".env"
    if not env.exists():
        print("\nAviso: .env nao encontrado. Copie .env.example para .env e preencha.")
    return EXIT_OK


def cmd_sources(args, settings: Settings) -> int:
    rows = []
    pendentes = []
    for source in _selected_sources(settings, args.source):
        if not source.tables:
            # Fonte recem-criada, ainda sem discover: precisa aparecer, senao
            # some da listagem justamente quando o usuario procura por ela.
            pendentes.append(source.name)
            rows.append([source.name, source.type, "(sem tabelas)", "-", "-", "-"])
            continue
        for table in source.tables:
            rows.append(
                [
                    source.name,
                    source.type,
                    table.qualified_name,
                    table.load_mode,
                    table.watermark_column or "-",
                    ",".join(table.primary_key) or "-",
                ]
            )
    print(_table(["FONTE", "TIPO", "TABELA", "MODO", "WATERMARK", "PK"], rows))
    for nome in pendentes:
        print(
            f"\n'{nome}' ainda nao tem tabelas. Para descobri-las:"
            f"\n  datalake discover -s {nome} --schemas"
            f"\n  datalake discover -s {nome} --schema <SCHEMA> "
            f"--write conf/sources/{nome}.yml --force"
        )
    return EXIT_OK


def cmd_test_connection(args, settings: Settings) -> int:
    from .connectors.registry import get_connector

    status = EXIT_OK
    for source in _selected_sources(settings, args.source):
        connector = get_connector(source, settings)
        try:
            connector.open()
            print(f"[ok]    {source.name}: {connector.describe()}")
        except Exception as exc:  # noqa: BLE001
            print(f"[falha] {source.name}: {exc}")
            status = EXIT_FAILED
        finally:
            connector.close()
    return status


def cmd_discover(args, settings: Settings) -> int:
    """Le o dicionario de dados da origem e propõe a configuracao das tabelas."""
    from .connectors.registry import get_connector
    from .discovery import inspect_schema, list_schemas, to_yaml

    source = settings.source(args.source)
    if source.type != "oracle":
        print(f"'discover' so funciona em fontes Oracle (a fonte '{source.name}' e "
              f"'{source.type}').", file=sys.stderr)
        return EXIT_CONFIG

    connector = get_connector(source, settings)
    try:
        connector.open()
        print(connector.describe())
        print()

        if args.find:
            from .discovery import find_objects

            objetos = find_objects(connector, args.find)
            if not objetos:
                print(f"Nada chamado '{args.find}' em nenhum schema visivel.")
                print("Se voce sabe que existe, o usuario nao tem permissao de leitura.")
                return EXIT_OK
            print(
                _table(
                    ["TIPO", "SCHEMA", "OBJETO", "APONTA PARA"],
                    [[o.object_type, o.owner, o.name, o.target or "-"] for o in objetos],
                )
            )
            print(f"\n{len(objetos)} objeto(s). View e sinonimo se leem como tabela: "
                  f"use schema + nome na configuracao da fonte.")
            return EXIT_OK

        if args.schemas or not args.schema:
            schemas = list_schemas(connector)
            print(_table(["SCHEMA", "OBJETOS", "TABELAS", "VIEWS"], schemas))
            if not args.schema:
                print("\nEscolha um e rode: datalake discover -s "
                      f"{source.name} --schema NOME")
            return EXIT_OK

        tables = inspect_schema(
            connector, args.schema, args.filter, top=args.top, min_rows=args.min_rows
        )
        print(
            _table(
                ["OBJETO", "TIPO", "LINHAS", "COLS", "PK", "WATERMARK", "MODO", "OBS"],
                [
                    [
                        t.name,
                        "view" if t.is_view else "tabela",
                        "?" if t.num_rows is None else f"{t.num_rows:,}",
                        len(t.columns),
                        ",".join(t.primary_key) or "-",
                        t.suggested_watermark or "-",
                        t.suggested_load_mode,
                        t.observacao,
                    ]
                    for t in sorted(tables, key=lambda x: x.name)
                ],
            )
        )
        print(f"\n{len(tables)} tabela(s) em {args.schema.upper()}")

        if args.write:
            destino = Path(args.write)
            if not destino.is_absolute():
                destino = settings.project_root / destino
            if destino.exists() and not args.force:
                print(f"\n{destino} ja existe. Use --force para sobrescrever.",
                      file=sys.stderr)
                return EXIT_FAILED
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(to_yaml(source.name, args.schema, tables), encoding="utf-8")
            print(f"\nConfiguracao gravada em {destino}")
            print("Revise as sugestoes de load_mode e watermark antes de rodar o ingest.")
        return EXIT_OK
    finally:
        connector.close()


def cmd_sql(args, settings: Settings) -> int:
    """Executa uma consulta de leitura direto na origem."""
    from .connectors.registry import get_connector

    source = settings.source(args.source)
    connector = get_connector(source, settings)
    if not hasattr(connector, "run_select"):
        print(f"'sql' nao suportado pela fonte '{source.name}' ({source.type}).",
              file=sys.stderr)
        return EXIT_CONFIG
    try:
        connector.open()
        descricao, linhas = connector.run_select(args.sql, args.limit)
        print(
            _table(
                [d[0] for d in descricao],
                [[_curto(valor, 40) for valor in linha] for linha in linhas],
            )
        )
        print(f"\n{len(linhas)} linha(s)"
              + (f" (limite {args.limit})" if len(linhas) >= args.limit else ""))
        return EXIT_OK
    finally:
        connector.close()


def cmd_peek(args, settings: Settings) -> int:
    """Mostra as primeiras linhas de um objeto da origem, sem carregar nada."""
    from .connectors.registry import get_connector

    source = settings.source(args.source)
    connector = get_connector(source, settings)
    if not hasattr(connector, "sample"):
        print(f"'peek' nao suportado pela fonte '{source.name}' ({source.type}).",
              file=sys.stderr)
        return EXIT_CONFIG

    try:
        connector.open()
        try:
            descricao, linhas = connector.sample(args.object, args.limit)
        except ConnectorError as exc:
            if "ORA-00942" in str(exc):
                # O Oracle usa o mesmo erro para "nao existe" e "sem permissao".
                raise ConnectorError(
                    f"{exc}\n\nORA-00942 quer dizer uma de duas coisas: o objeto "
                    f"nao existe com esse nome, ou seu usuario nao tem SELECT nele.\n"
                    f"Para descobrir qual: datalake discover -s {source.name} "
                    f"--find {args.object.split('.')[-1]}"
                ) from exc
            raise
        nomes = [d[0] for d in descricao]

        print(f"--- {args.object}: {len(linhas)} primeira(s) linha(s) ---\n")
        print(
            _table(
                nomes,
                [[_curto(valor) for valor in linha] for linha in linhas],
            )
        )
        print("\n--- colunas ---")
        print(
            _table(
                ["COLUNA", "TIPO ORACLE", "PREC", "ESC", "ACEITA NULO"],
                [
                    [d[0], getattr(d[1], "name", d[1]), d[4] or "", d[5] or "",
                     "sim" if d[6] else "nao"]
                    for d in descricao
                ],
            )
        )
        if not linhas:
            print("\nObjeto acessivel, porem sem linhas.")
        return EXIT_OK
    finally:
        connector.close()


def _curto(valor: Any, largura: int = 30) -> str:
    """Encurta valores longos para a tabela nao virar uma parede de texto."""
    if valor is None:
        return ""
    texto = str(valor).replace("\n", " ").replace("\r", " ")
    return texto if len(texto) <= largura else texto[: largura - 1] + "~"


def cmd_ingest(args, settings: Settings) -> int:
    from .layers import bronze

    control = ControlDB(settings.control_db)
    run_id = args.run_id or new_run_id()
    results = []
    for source in _selected_sources(settings, args.source):
        results.extend(
            bronze.ingest_source(
                settings,
                source,
                control,
                run_id,
                tables=args.table,
                full=args.full,
                dry_run=args.dry_run,
            )
        )

    print()
    print(
        _table(
            ["FONTE", "TABELA", "STATUS", "LINHAS", "ARQ", "MB", "WATERMARK", "OBS"],
            [
                [
                    r.source,
                    r.table,
                    r.status,
                    f"{r.rows:,}",
                    r.files,
                    f"{r.bytes_written / 1_048_576:.1f}",
                    r.watermark_to or "-",
                    (r.message or "")[:60],
                ]
                for r in results
            ],
        )
    )
    ok, failed = _summary(results)
    print(f"\nBronze: {ok} ok, {failed} com falha (run_id={run_id})")
    return EXIT_FAILED if failed else EXIT_OK


def cmd_silver(args, settings: Settings) -> int:
    from .layers import silver

    control = ControlDB(settings.control_db)
    run_id = args.run_id or new_run_id()
    results = []
    for source in _selected_sources(settings, args.source):
        results.extend(silver.build_source(settings, source, control, run_id, args.table))

    print()
    print(
        _table(
            ["FONTE", "TABELA", "STATUS", "LINHAS", "SEG", "OBS"],
            [
                [r.source, r.table, r.status, f"{r.rows:,}", f"{r.duration_s:.1f}",
                 (r.message or "")[:60]]
                for r in results
            ],
        )
    )
    ok, failed = _summary(results)
    print(f"\nSilver: {ok} ok, {failed} com falha")
    return EXIT_FAILED if failed else EXIT_OK


def cmd_gold(args, settings: Settings) -> int:
    from .layers import gold

    control = ControlDB(settings.control_db)
    run_id = args.run_id or new_run_id()
    results = gold.build_all(settings, control, run_id, args.model)

    print()
    print(
        _table(
            ["MODELO", "STATUS", "LINHAS", "SEG", "OBS"],
            [
                [r.model, r.status, f"{r.rows:,}", f"{r.duration_s:.1f}", (r.message or "")[:70]]
                for r in results
            ],
        )
    )
    ok, failed = _summary(results)
    print(f"\nGold: {ok} ok, {failed} com falha")
    return EXIT_FAILED if failed else EXIT_OK


def cmd_quality(args, settings: Settings) -> int:
    from .quality.checks import run_table_checks, summarize

    control = ControlDB(settings.control_db)
    run_id = args.run_id or new_run_id()
    results = []
    for source in _selected_sources(settings, args.source):
        tables = [source.table(t) for t in args.table] if args.table else source.tables
        for table in tables:
            results.extend(run_table_checks(settings, source, table))

    control.save_quality(run_id, [r.as_row() for r in results])
    print()
    print(
        _table(
            ["FONTE", "TABELA", "TESTE", "COLUNA", "STATUS", "OBSERVADO", "DETALHE"],
            [
                [r.source, r.table_name, r.check_name, r.column_name or "-", r.status,
                 "" if r.observed is None else r.observed, (r.details or "")[:50]]
                for r in results
            ],
        )
    )
    passed, failed, errors = summarize(results)
    print(f"\nQualidade: {passed} aprovados, {failed} reprovados, {errors} com erro")
    return EXIT_FAILED if any(r.blocking for r in results) else EXIT_OK


def cmd_catalog(args, settings: Settings) -> int:
    from .catalog.builder import build_catalog

    entries = build_catalog(settings)
    print(
        _table(
            ["CAMADA", "OBJETO", "LINHAS", "LOCAL"],
            [[e.schema, e.name, f"{e.rows:,}", e.location] for e in entries],
        )
    )
    print(f"\nCatalogo: {settings.catalog_db}")
    return EXIT_OK


def cmd_run(args, settings: Settings) -> int:
    """Pipeline completo: bronze -> silver -> gold -> qualidade -> catalogo."""
    run_id = new_run_id()
    args.run_id = run_id
    print(f"=== Execucao {run_id} ===")

    status = EXIT_OK
    for name, command in (
        ("INGEST", cmd_ingest),
        ("SILVER", cmd_silver),
        ("GOLD", cmd_gold),
        ("QUALIDADE", cmd_quality),
        ("CATALOGO", cmd_catalog),
    ):
        if name == "GOLD" and args.skip_gold:
            continue
        print(f"\n----- {name} -----")
        result = command(args, settings)
        if result != EXIT_OK:
            status = EXIT_FAILED
            if name in ("INGEST", "SILVER") and not args.keep_going:
                print(f"\nEtapa {name} falhou; interrompendo (use --keep-going para seguir).")
                return status
    print(f"\n=== Fim da execucao {run_id}: {'ok' if status == EXIT_OK else 'com falhas'} ===")
    return status


def cmd_state(args, settings: Settings) -> int:
    control = ControlDB(settings.control_db)
    print("--- Watermarks ---")
    print(
        _table(
            ["FONTE", "TABELA", "STATUS", "WATERMARK", "ULTIMA CARGA", "LINHAS", "TOTAL"],
            control.list_state(),
        )
    )
    print("\n--- Ultimas execucoes ---")
    print(
        _table(
            ["INICIO", "RUN", "CAMADA", "FONTE", "TABELA", "STATUS", "LINHAS", "SEG", "OBS"],
            [
                [r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], (r[8] or "")[:50]]
                for r in control.recent_runs(args.limit)
            ],
        )
    )
    return EXIT_OK


def cmd_reset(args, settings: Settings) -> int:
    control = ControlDB(settings.control_db)
    source = settings.source(args.source)
    table = source.table(args.table).key if args.table else None
    alvo = f"{source.name}.{table}" if table else source.name
    if not args.yes:
        resposta = input(f"Zerar o watermark de {alvo}? A proxima carga sera total. [s/N] ")
        if resposta.strip().lower() not in ("s", "sim", "y", "yes"):
            print("Cancelado.")
            return EXIT_OK
    control.reset_state(source.name, table)
    print(f"Watermark de {alvo} removido.")
    return EXIT_OK


def cmd_query(args, settings: Settings) -> int:
    from .duck import connect
    from .layers.gold import register_silver_views

    con = connect(settings)
    try:
        register_silver_views(con, settings)
        for name, directory in _gold_datasets(settings).items():
            from .duck import quote, quote_literal
            from .storage.paths import glob_parquet

            con.execute(
                f"CREATE OR REPLACE VIEW {quote(name)} AS SELECT * FROM "
                f"read_parquet({quote_literal(glob_parquet(directory))})"
            )
        result = con.execute(args.sql)
        headers = [d[0] for d in result.description]
        print(_table(headers, result.fetchall()))
    finally:
        con.close()
    return EXIT_OK


def _gold_datasets(settings: Settings) -> dict[str, Path]:
    root = settings.gold
    if not root.is_dir():
        return {}
    return {
        p.name: p for p in sorted(root.iterdir()) if p.is_dir() and any(p.glob("*.parquet"))
    }


# ---------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datalake",
        description="Datalake local: Oracle -> bronze -> silver -> gold (Parquet + DuckDB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--project", type=Path, default=None, help="raiz do projeto")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING, ERROR")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_source_args(sp, with_table: bool = True):
        sp.add_argument("-s", "--source", help="nome da fonte (padrao: todas)")
        if with_table:
            sp.add_argument(
                "-t", "--table", action="append", help="tabela (pode repetir)"
            )
        sp.add_argument("--run-id", help="reaproveita um run_id existente")

    p = sub.add_parser("init", help="cria diretorios e o banco de controle")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("sources", help="lista fontes e tabelas")
    p.add_argument("-s", "--source")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("test-connection", help="testa a conexao com as origens")
    p.add_argument("-s", "--source")
    p.set_defaults(func=cmd_test_connection)

    p = sub.add_parser("discover", help="le o dicionario de dados e propõe a configuracao")
    p.add_argument("-s", "--source", required=True)
    p.add_argument("--schema", help="schema (owner) a inspecionar")
    p.add_argument("--schemas", action="store_true", help="so lista os schemas visiveis")
    p.add_argument("--find", metavar="NOME",
                   help="procura um nome em todos os schemas, em tabela, view, "
                        "sinonimo ou view materializada. Ex.: --find VEI")
    p.add_argument("--filter", action="append",
                   help="filtro LIKE no nome da tabela; repita para varios: "
                        "--filter 'VEI%%' --filter 'FAT%%'")
    p.add_argument("--top", type=int, help="so as N maiores tabelas (por volume estimado)")
    p.add_argument("--min-rows", type=int, dest="min_rows",
                   help="ignora tabelas com menos linhas que isso")
    p.add_argument("--write", help="grava o YAML gerado no caminho informado")
    p.add_argument("--force", action="store_true", help="sobrescreve o arquivo existente")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("sql", help="consulta de leitura direto na origem")
    p.add_argument("-s", "--source", required=True)
    p.add_argument("sql", help="SELECT ... (somente leitura)")
    p.add_argument("-n", "--limit", type=int, default=100)
    p.set_defaults(func=cmd_sql)

    p = sub.add_parser("peek", help="mostra as primeiras linhas de um objeto da origem")
    p.add_argument("-s", "--source", required=True)
    p.add_argument("-o", "--object", required=True,
                   metavar="OBJETO", help="OBJETO ou SCHEMA.OBJETO, ex.: CNP.VEI_VEI")
    p.add_argument("-n", "--limit", type=int, default=10, help="linhas (padrao 10)")
    p.set_defaults(func=cmd_peek)

    p = sub.add_parser("ingest", help="origem -> bronze")
    add_source_args(p)
    p.add_argument("--full", action="store_true", help="ignora o watermark e recarrega tudo")
    p.add_argument("--dry-run", action="store_true", help="so conta as linhas")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("silver", help="bronze -> silver")
    add_source_args(p)
    p.set_defaults(func=cmd_silver)

    p = sub.add_parser("gold", help="silver -> gold")
    p.add_argument("-m", "--model", action="append", help="modelo (pode repetir)")
    p.add_argument("--run-id")
    p.set_defaults(func=cmd_gold)

    p = sub.add_parser("quality", help="testes de qualidade sobre a silver")
    add_source_args(p)
    p.set_defaults(func=cmd_quality)

    p = sub.add_parser("catalog", help="atualiza o catalogo lake.duckdb")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("run", help="pipeline completo")
    add_source_args(p)
    p.add_argument("--full", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-gold", action="store_true")
    p.add_argument("--keep-going", action="store_true", help="segue mesmo com falhas")
    p.add_argument("-m", "--model", action="append")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("state", help="watermarks e historico")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.set_defaults(func=cmd_state)

    p = sub.add_parser("reset", help="zera o watermark de uma fonte/tabela")
    p.add_argument("-s", "--source", required=True)
    p.add_argument("-t", "--table")
    p.add_argument("-y", "--yes", action="store_true", help="nao pergunta")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("query", help="executa SQL sobre silver e gold")
    p.add_argument("sql")
    p.set_defaults(func=cmd_query)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.project)
    except ConfigError as exc:
        print(f"Erro de configuracao: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    setup_logging(args.log_level or settings.log_level, settings.log_dir)

    try:
        return args.func(args, settings)
    except ConfigError as exc:
        log.error("Erro de configuracao: %s", exc)
        return EXIT_CONFIG
    except ConnectorError as exc:
        # Falha de conexao ja vem com diagnostico pronto; o traceback so atrapalha.
        print(f"\n{exc}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuario")
        return EXIT_FAILED
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha inesperada: %s", exc)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
