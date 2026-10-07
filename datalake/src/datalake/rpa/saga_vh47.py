"""RPA SAGA2 - VH47: portal -> PDFs -> planilha. Ponto de entrada.

    python -m datalake.rpa.saga_vh47                  # fluxo completo (abre o navegador)
    python -m datalake.rpa.saga_vh47 --so-listar      # so mostra o que falta, nao baixa
    python -m datalake.rpa.saga_vh47 --importar PASTA # processa PDFs ja baixados a mao
    python -m datalake.rpa.saga_vh47 --testar-pdf X.pdf  # so extrai e mostra (nao grava)
    python -m datalake.rpa.saga_vh47 --status         # o que o controle sabe

Idempotente: rodar de novo sem relatorio novo nao baixa nem lanca nada.
Codigo de saida: 0 = ok; 2 = terminou, mas algum arquivo deu erro; 1 = falha geral.
Documentacao: docs/saga-vh47.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import yaml

from ..config import _expand, load_settings
from .controle import Controle, ItemLista, sha256_arquivo
from .pdf_extrator import ErroExtracao, Layout, extrair_pdf, texto_do_pdf, validar_pdf
from .planilha import ConfigPlanilha, ErroPlanilha, Planilha
from .saga_portal import (ConfigPortal, ErroPortal, SessaoPortal, carregar_login_automatico,
                          nome_seguro)
from .valores import chave_numerica, formatar_brl

log = logging.getLogger("rpa.saga_vh47")

RAIZ_PROJETO = Path(__file__).resolve().parents[3]
CONFIG_PADRAO = RAIZ_PROJETO / "conf" / "rpa" / "saga_vh47.yml"
ENV_ESTAVEL = Path(r"C:\datalake\.env")


# ----------------------------------------------------------------- configuracao

class Config:
    def __init__(self, caminho: Path, pasta: Path | None = None):
        with open(caminho, encoding="utf-8") as f:
            bruto = _expand(yaml.safe_load(f) or {})
        self.pasta = Path(pasta or bruto.get("pasta") or RAIZ_PROJETO / "data" / "rpa" / "saga_vh47")
        if not self.pasta.is_absolute():
            self.pasta = (RAIZ_PROJETO / self.pasta).resolve()
        lista = bruto.get("lista") or {}
        self.dns = [chave_numerica(d) for d in str(lista.get("dn") or "").split(",") if d.strip()]
        # Regra critica: a quantidade de fechamentos do mes NAO e configurada;
        # vem do Portal Rede. Qualquer "esperado_por_mes" no YAML e ignorado.
        self.esperado_por_mes = 0
        self.portal = ConfigPortal.from_dict(bruto.get("portal") or {}, lista, self.pasta)
        try:
            self.layouts = [Layout.from_dict(l) for l in (bruto.get("extracao") or {}).get("layouts") or []]
        except ValueError as exc:
            raise ErroExtracao(f"extracao: {exc}") from exc
        if not self.layouts:
            raise ErroExtracao("extracao.layouts vazio no YAML")
        tipos = {c.nome: c.tipo for l in self.layouts for c in l.campos}
        self._planilha = bruto.get("planilha") or {}
        self._tipos = tipos

    def planilha(self) -> ConfigPlanilha:
        """Separado: --testar-pdf e --status nao precisam da planilha configurada."""
        return ConfigPlanilha.from_dict(self._planilha, self._tipos, self.pasta)

    @property
    def pasta_pdfs(self) -> Path:
        return self.pasta / "pdfs"

    @property
    def controle_db(self) -> Path:
        return self.pasta / "controle.sqlite"


def configurar_log(pasta_logs: Path, nivel: str = "INFO") -> None:
    raiz = logging.getLogger()
    if any(getattr(h, "_rpa_saga", False) for h in raiz.handlers):
        return
    raiz.setLevel(getattr(logging, nivel.upper(), logging.INFO))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    console._rpa_saga = True  # type: ignore[attr-defined]
    raiz.addHandler(console)
    pasta_logs.mkdir(parents=True, exist_ok=True)
    arquivo = RotatingFileHandler(pasta_logs / "saga_vh47.log", maxBytes=5 * 1024 * 1024,
                                  backupCount=5, encoding="utf-8")
    arquivo.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    arquivo._rpa_saga = True  # type: ignore[attr-defined]
    raiz.addHandler(arquivo)


def log_erro_arquivo(nome: str, motivo: str) -> None:
    log.error("Arquivo: %s", nome)
    log.error("Status: ERRO")
    log.error("Motivo: %s", motivo)


# ----------------------------------------------------------------- processamento

class Processador:
    """Um arquivo: (PDF no disco) -> extracao -> planilha -> controle."""

    def __init__(self, cfg: Config, controle: Controle):
        self.cfg = cfg
        self.controle = controle
        self._planilha: Planilha | None = None
        self.resumo: dict[str, Any] = {"processados": 0, "duplicados": 0, "erros": 0,
                                       "inseridas": 0, "atualizadas": 0, "divergentes": 0, "sem_mudanca": 0}

    @property
    def planilha(self) -> Planilha:
        if self._planilha is None:
            self._planilha = Planilha(self.cfg.planilha())
        return self._planilha

    def processar(self, item: ItemLista, pdf: Path) -> bool:
        """True se finalizou (processado/duplicado). ErroPlanilha sobe: parar e seguro."""
        sha = sha256_arquivo(pdf)
        self.controle.marcar_baixado(item.id, sha, pdf)
        original = self.controle.processado_com_hash(sha, exceto=item.id)
        if original:
            log.info("Mesmo conteudo de um arquivo ja processado (%s): nao lanco de novo", original)
            self.controle.marcar_duplicado(item.id, original)
            self.resumo["duplicados"] += 1
            return True

        log.info("Extraindo dados do PDF")
        try:
            resultado = extrair_pdf(pdf, self.cfg.layouts)
        except ErroExtracao as exc:
            log_erro_arquivo(pdf.name, str(exc))
            log.error("PDF mantido para analise: %s", pdf)
            self.controle.marcar_erro(item.id, str(exc))
            self.resumo["erros"] += 1
            return False
        for aviso in resultado.avisos:
            log.debug(aviso)

        for reg in resultado.registros:
            log.info("SG identificada: %s", reg.get("sg"))
            if reg.get("valor_total") is not None:
                log.info("Valor total identificado: %s", formatar_brl(reg["valor_total"]))

        try:
            acoes = self.planilha.upsert(resultado.registros)
        except ErroPlanilha as exc:
            self.controle.marcar_erro(item.id, f"planilha: {exc}")
            self.resumo["erros"] += 1
            raise
        feitos = []
        for a in acoes:
            if a.acao == "inserida":
                log.info("Registro inserido na planilha (SG %s, linha %d)", a.chave, a.linha)
                self.resumo["inseridas"] += 1
            elif a.acao == "atualizada":
                log.info("SG %s ja estava na planilha (linha %d): %s", a.chave, a.linha, a.detalhe)
                self.resumo["atualizadas"] += 1
            elif a.acao == "divergente":
                log.warning("SG %s ja estava na planilha com valor DIFERENTE (linha %d), mantido: %s",
                            a.chave, a.linha, a.detalhe)
                self.resumo["divergentes"] += 1
            else:
                log.info("SG %s ja estava na planilha (linha %d), nada a mudar", a.chave, a.linha)
                self.resumo["sem_mudanca"] += 1
            feitos.append({"chave": a.chave, "dados": a.dados, "acao": a.acao, "detalhe": a.detalhe})
        self.controle.marcar_processado(item.id, resultado.layout, feitos)
        self.resumo["processados"] += 1
        return True


def caminho_pdf(cfg: Config, item: ItemLista) -> Path:
    return cfg.pasta_pdfs / f"{item.ano:04d}" / f"{item.mes:02d}" / (item.dn or "sem_dn") / nome_seguro(item.nome)


def pdf_ja_baixado(controle: Controle, item: ItemLista) -> Path | None:
    """Reaproveita o PDF de uma tentativa anterior (erro de extracao/planilha)."""
    linha = controle.status(item.id)
    if not linha or not linha["caminho_pdf"]:
        return None
    pdf = Path(linha["caminho_pdf"])
    try:
        validar_pdf(pdf)
    except ErroExtracao:
        return None
    if linha["sha256"] and sha256_arquivo(pdf) != linha["sha256"]:
        return None
    return pdf


def avisar_lacunas(cfg: Config, itens: list[ItemLista]) -> None:
    """Meses (ja fechados) com menos relatorios que o esperado no portal."""
    if not cfg.esperado_por_mes:
        return
    hoje = dt.date.today()
    por_mes: dict[tuple[int, int], int] = {}
    for it in itens:
        por_mes[(it.ano, it.mes)] = por_mes.get((it.ano, it.mes), 0) + 1
    for (ano, mes), n in sorted(por_mes.items()):
        if (ano, mes) != (hoje.year, hoje.month) and n < cfg.esperado_por_mes:
            log.warning("%04d-%02d: o portal lista %d relatorio(s); o normal e ~%d. Pode faltar publicacao.",
                        ano, mes, n, cfg.esperado_por_mes)


# ------------------------------------------------------------------- comandos

def cmd_portal(cfg: Config, controle: Controle, proc: Processador, so_listar: bool) -> int:
    if not cfg.dns:
        log.error("Defina SAGA_DN no .env (DN da concessionaria; varios separados por virgula).")
        return 1
    if not so_listar:
        cfg.planilha()  # falha cedo se a planilha nao estiver configurada
        proc.planilha.checar_pode_gravar()
    login = carregar_login_automatico(RAIZ_PROJETO)
    with SessaoPortal(cfg.portal, cfg.pasta / "tmp_downloads") as sessao:
        sessao.garantir_login(login)
        sessao.ir_para_lista()
        todos = sessao.listar()
        log.info("%d arquivos encontrados", len(todos))
        itens = [i for i in todos if i.dn in cfg.dns]
        outros = sorted({i.dn for i in todos} - set(cfg.dns))
        if outros:
            log.info("Ignorados %d arquivo(s) de outros DN (%s)", len(todos) - len(itens), ", ".join(outros))
        if not itens:
            log.warning("Nenhum arquivo do(s) DN %s na lista.", ", ".join(cfg.dns))
            return 0
        controle.registrar_listagem(itens)
        avisar_lacunas(cfg, itens)
        pendentes = controle.pendentes(itens)
        log.info("Identificados %d arquivo(s) ainda nao processados", len(pendentes))
        for it in pendentes:
            log.info("  pendente: %s", it.rotulo)
        if so_listar:
            return 0

        for it in pendentes:  # do mais antigo para o mais novo
            log.info("---- %s", it.rotulo)
            try:
                pdf = pdf_ja_baixado(controle, it)
                if pdf:
                    log.info("PDF ja baixado antes, reaproveitado: %s", pdf.name)
                else:
                    log.info("Iniciando download: %s", it.nome)
                    pdf = sessao.baixar(it, caminho_pdf(cfg, it))
                    log.info("Download concluido (%d KB)", pdf.stat().st_size // 1024)
                proc.processar(it, pdf)
            except ErroPlanilha as exc:
                log_erro_arquivo(it.nome, f"planilha: {exc}")
                log.error("Parando: sem gravar na planilha nao e seguro seguir. Os demais ficam para a proxima.")
                return 2
            except ErroPortal as exc:
                log_erro_arquivo(it.nome, str(exc))
                controle.marcar_erro(it.id, str(exc))
                proc.resumo["erros"] += 1
    return 2 if proc.resumo["erros"] else 0


def cmd_importar(cfg: Config, controle: Controle, proc: Processador, pasta: Path) -> int:
    """PDFs baixados a mao: mesma extracao, mesma planilha, mesmo controle."""
    pdfs = sorted(p for p in Path(pasta).rglob("*") if p.suffix.lower() == ".pdf")
    log.info("%d PDF(s) em %s", len(pdfs), pasta)
    dn = cfg.dns[0] if cfg.dns else ""
    for pdf in pdfs:
        momento = dt.datetime.fromtimestamp(pdf.stat().st_mtime)
        # identidade pelo conteudo: o mesmo PDF importado de novo cai no mesmo id
        item = ItemLista(ano=momento.year, mes=momento.month, regional="(manual)", dn=dn,
                         nome=pdf.name, id_fixo="manual-" + sha256_arquivo(pdf)[:16])
        linha = controle.status(item.id)
        if linha and linha["status"] in ("processado", "duplicado"):
            log.info("%s: ja processado em %s, ignorado", pdf.name, linha["processado_em"])
            continue
        controle.registrar_listagem([item])
        log.info("---- %s", pdf.name)
        try:
            validar_pdf(pdf)
            proc.processar(item, pdf)
        except ErroExtracao as exc:
            log_erro_arquivo(pdf.name, str(exc))
            controle.marcar_erro(item.id, str(exc))
            proc.resumo["erros"] += 1
        except ErroPlanilha as exc:
            log_erro_arquivo(pdf.name, f"planilha: {exc}")
            return 2
    return 2 if proc.resumo["erros"] else 0


def cmd_testar_pdf(cfg: Config, pdf: Path, mostrar_texto: bool) -> int:
    try:
        paginas = validar_pdf(pdf)
        texto = texto_do_pdf(pdf)
        if mostrar_texto:
            print(texto)
        from .pdf_extrator import extrair_texto

        r = extrair_texto(texto, cfg.layouts)
    except ErroExtracao as exc:
        log_erro_arquivo(pdf.name, str(exc))
        return 1
    log.info("%s: %d pagina(s), layout '%s', %d registro(s)", pdf.name, paginas, r.layout, len(r.registros))
    for reg in r.registros:
        log.info("  %s", json.dumps(reg, ensure_ascii=False, default=str))
    for a in r.avisos:
        log.info("  aviso: %s", a)
    return 0


def cmd_status(controle: Controle) -> int:
    log.info("Controle: %s", controle.caminho)
    for status, n in sorted(controle.contagem().items()):
        log.info("  %-11s %d", status, n)
    with controle._con() as con:
        for l in con.execute("SELECT ano, mes, dn, nome, status, erro FROM arquivos "
                             "WHERE status NOT IN ('processado','duplicado') ORDER BY ano, mes, nome"):
            log.info("  %04d-%02d DN %s %s -> %s %s", l["ano"], l["mes"], l["dn"], l["nome"],
                     l["status"], l["erro"] or "")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="saga_vh47", description="RPA SAGA2 - VH47 -> planilha")
    ap.add_argument("--config", type=Path, default=CONFIG_PADRAO)
    ap.add_argument("--pasta", type=Path, help="pasta de trabalho (padrao: 'pasta' do YAML)")
    ap.add_argument("--so-listar", action="store_true", help="le a lista e mostra o que falta; nao baixa")
    ap.add_argument("--importar", type=Path, metavar="PASTA", help="processa PDFs ja baixados")
    ap.add_argument("--testar-pdf", type=Path, metavar="PDF", help="so extrai e mostra (nao grava)")
    ap.add_argument("--texto", action="store_true", help="com --testar-pdf: imprime o texto lido do PDF")
    ap.add_argument("--status", action="store_true", help="resumo do controle")
    ap.add_argument("--headless", action="store_true", help="sem janela (so com sessao ja guardada)")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    # O .env estavel do servidor (C:\datalake\.env) e o que o operador edita; o do
    # projeto e uma copia feita na instalacao. O estavel vem primeiro.
    if ENV_ESTAVEL.is_file():
        try:
            from dotenv import load_dotenv

            load_dotenv(ENV_ESTAVEL, override=False)
        except ImportError:
            pass
    settings = load_settings(RAIZ_PROJETO)  # carrega o .env do projeto
    try:
        cfg = Config(args.config, args.pasta)
    except (ErroExtracao, ErroPortal, OSError, KeyError) as exc:
        configurar_log(settings.log_dir / "rpa", args.log_level)
        log.error("Configuracao invalida (%s): %s", args.config, exc)
        return 1
    # log junto com PDFs e controle: fora da pasta do codigo, que a atualizacao apaga
    configurar_log(cfg.pasta / "logs", args.log_level)
    if args.headless:
        cfg.portal.headless = True

    if args.testar_pdf:
        return cmd_testar_pdf(cfg, args.testar_pdf, args.texto)

    controle = Controle(cfg.controle_db)
    if args.status:
        return cmd_status(controle)

    run_id = f"{dt.datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    log.info("Iniciando automacao SAGA2 - VH47 (execucao %s)", run_id)
    controle.iniciar_execucao(run_id)
    proc = Processador(cfg, controle)
    codigo = 1
    try:
        if args.importar:
            codigo = cmd_importar(cfg, controle, proc, args.importar)
        else:
            codigo = cmd_portal(cfg, controle, proc, args.so_listar)
    except (ErroPortal, ErroPlanilha) as exc:
        log.error("ERRO: %s", exc)
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuario")
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha inesperada: %s", exc)
    finally:
        status = {0: "ok", 2: "com_erros"}.get(codigo, "falhou")
        controle.finalizar_execucao(run_id, status, proc.resumo)
        log.info("Fim: %s | %s", status, ", ".join(f"{k}={v}" for k, v in proc.resumo.items()))
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
