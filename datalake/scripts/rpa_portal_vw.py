# -*- coding: utf-8 -*-
"""
RPA do Portal Rede VW: faz login e entra no usuario especifico.

    python C:\\datalake\\rpa_portal_vw.py              # roda sem janela
    python C:\\datalake\\rpa_portal_vw.py --visivel    # mostra o navegador
    python C:\\datalake\\rpa_portal_vw.py --pausar     # para no fim, com o inspetor aberto
    python C:\\datalake\\rpa_portal_vw.py --gravar     # grava cliques -> codigo (descobrir seletores)
    python C:\\datalake\\rpa_portal_vw.py --alvo "NOME"  # outro usuario so desta vez

Credenciais vem do .env (C:\\datalake\\.env), nunca do codigo:
    RPA_PORTALVW_USUARIO, RPA_PORTALVW_SENHA, RPA_PORTALVW_ALVO

O que clicar vem do rpa_portal_vw.yml (ao lado deste script) ou, na falta
dele, de conf/rpa/portal_vw.yml do projeto.

Toda execucao deixa um print da tela em logs/rpa/ -- inclusive quando falha,
junto com o HTML da pagina, para saber em que passo parou. A senha nunca
aparece em log nem em print (o campo de senha mostra so bolinhas).

Saida: 0 = entrou no usuario; 1 = falhou (motivo na tela e em logs/rpa/).
"""
from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

import yaml

AQUI = Path(__file__).resolve().parent
LAKE = Path(r"C:\datalake") if os.name == "nt" else AQUI.parent
PROJETO_CONF = AQUI.parent / "conf" / "rpa" / "portal_vw.yml"

ENV_USUARIO = "RPA_PORTALVW_USUARIO"
ENV_SENHA = "RPA_PORTALVW_SENHA"
ENV_ALVO = "RPA_PORTALVW_ALVO"


class FalhaRPA(Exception):
    """Passo que nao deu certo, com mensagem para quem opera."""


def carregar_env() -> None:
    """Le o .env estavel (C:\\datalake\\.env) e o do projeto, sem sobrescrever
    o que ja estiver no ambiente."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for env in (LAKE / ".env", AQUI.parent / ".env", AQUI / ".env"):
        if env.is_file():
            load_dotenv(env, override=False)


def achar_config(caminho: str | None) -> Path:
    candidatos = [Path(caminho)] if caminho else [AQUI / "rpa_portal_vw.yml", PROJETO_CONF]
    for c in candidatos:
        if c.is_file():
            return c
    raise FalhaRPA("Nao achei a configuracao da RPA: " + ", ".join(map(str, candidatos)))


def ler_config(caminho: Path) -> dict:
    with open(caminho, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not cfg.get("url"):
        raise FalhaRPA(f"{caminho}: falta 'url'.")
    cfg.setdefault("navegador", "msedge")
    cfg.setdefault("timeout_s", 60)
    cfg.setdefault("login", {})
    cfg.setdefault("usuario_alvo", {})
    cfg.setdefault("confirmacao", "")
    return cfg


def credenciais(alvo_cli: str | None) -> tuple[str, str, str]:
    usuario = os.environ.get(ENV_USUARIO, "").strip()
    senha = os.environ.get(ENV_SENHA, "")
    alvo = (alvo_cli or os.environ.get(ENV_ALVO, "")).strip()
    faltando = [n for n, v in ((ENV_USUARIO, usuario), (ENV_SENHA, senha), (ENV_ALVO, alvo)) if not v]
    if faltando:
        raise FalhaRPA(
            "Falta(m) no .env: " + ", ".join(faltando)
            + f"\n  Abra {LAKE / '.env'} no Bloco de Notas e preencha (modelo no .env.example)."
        )
    return usuario, senha, alvo


def seletor(texto: str | None, alvo: str = "") -> str:
    """Normaliza o seletor do YAML (tira quebras de linha do '>-') e troca {alvo}."""
    return " ".join((texto or "").split()).replace("{alvo}", alvo)


def visivel(page, sel: str, timeout_ms: int):
    """Primeiro elemento visivel que casa com o seletor, ou None."""
    loc = page.locator(f"{sel} >> visible=true").first
    try:
        loc.wait_for(state="visible", timeout=timeout_ms)
        return loc
    except Exception:
        return None


def obrigatorio(page, sel: str, timeout_ms: int, passo: str):
    loc = visivel(page, sel, timeout_ms)
    if loc is None:
        raise FalhaRPA(f"Passo '{passo}': nao achei na tela o seletor  {sel}\n"
                       "  Ajuste no rpa_portal_vw.yml (use GRAVAR-PORTAL-VW.bat para descobrir).")
    return loc


def esperar_tela(page, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass  # sites com polling nunca ficam "idle"; segue com o que carregou


def fazer_login(page, cfg: dict, usuario: str, senha: str, timeout_ms: int) -> None:
    lg = cfg["login"]
    if lg.get("abrir"):
        obrigatorio(page, seletor(lg["abrir"]), timeout_ms, "abrir login").click()
        esperar_tela(page, timeout_ms)

    sel_usuario, sel_senha, sel_entrar = (seletor(lg.get(k)) for k in ("usuario", "senha", "entrar"))
    obrigatorio(page, sel_usuario, timeout_ms, "campo usuario").fill(usuario)
    print("  ok: usuario preenchido")

    # Login em duas etapas (usuario -> Avancar -> senha): se a senha ainda nao
    # esta na tela, avanca primeiro.
    campo_senha = visivel(page, sel_senha, 2000)
    if campo_senha is None:
        obrigatorio(page, sel_entrar, timeout_ms, "botao avancar").click()
        campo_senha = obrigatorio(page, sel_senha, timeout_ms, "campo senha")
    campo_senha.fill(senha)
    print("  ok: senha preenchida")

    botao = visivel(page, sel_entrar, 3000)
    if botao is not None:
        botao.click()
    else:
        campo_senha.press("Enter")
    esperar_tela(page, timeout_ms)

    # Se o campo de senha continua la, o portal recusou (senha errada, captcha...)
    if visivel(page, sel_senha, 3000) is not None:
        raise FalhaRPA("O login nao passou: a tela de senha continua aberta. "
                       "Confira usuario/senha no .env, ou se o portal pediu captcha/codigo.")
    print("  ok: login feito")


def entrar_no_usuario(page, cfg: dict, alvo: str, timeout_ms: int) -> None:
    ua = cfg["usuario_alvo"]
    if ua.get("abrir"):
        obrigatorio(page, seletor(ua["abrir"], alvo), timeout_ms, "abrir lista de usuarios").click()
    if ua.get("buscar"):
        obrigatorio(page, seletor(ua["buscar"], alvo), timeout_ms, "buscar usuario").fill(alvo)
    if ua.get("escolher"):
        obrigatorio(page, seletor(ua["escolher"], alvo), timeout_ms, f"escolher usuario '{alvo}'").click()
        esperar_tela(page, timeout_ms)
    if cfg.get("confirmacao"):
        obrigatorio(page, seletor(cfg["confirmacao"], alvo), timeout_ms, "confirmacao")
    print(f"  ok: dentro do usuario '{alvo}'")


def abrir_navegador(pw, nome: str, visivel_: bool):
    opcoes = {"headless": not visivel_}
    if nome in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(channel=nome, **opcoes)
        except Exception as e:  # sem Edge/Chrome instalado: tenta o Chromium do Playwright
            print(f"  aviso: nao abri o {nome} ({str(e).splitlines()[0]}); tentando o Chromium")
    return pw.chromium.launch(**opcoes)


def gravar(url: str) -> int:
    """Abre o navegador + janela do Playwright que escreve o codigo de cada clique."""
    print("  Faca o caminho no navegador que abriu (login + escolher o usuario).")
    print("  A outra janela mostra os seletores -- copie para o rpa_portal_vw.yml.")
    return subprocess.call([sys.executable, "-m", "playwright", "codegen",
                            "--channel", "msedge" if os.name == "nt" else "chromium", url])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RPA do Portal Rede VW")
    ap.add_argument("--config", help="caminho do YAML (padrao: rpa_portal_vw.yml ao lado do script)")
    ap.add_argument("--alvo", help="usuario a escolher (padrao: RPA_PORTALVW_ALVO do .env)")
    ap.add_argument("--url", help="outra URL (testes)")
    ap.add_argument("--visivel", action="store_true", help="mostra o navegador")
    ap.add_argument("--pausar", action="store_true", help="para no fim com o inspetor aberto")
    ap.add_argument("--gravar", action="store_true", help="grava cliques para descobrir seletores")
    ap.add_argument("--saida", help="pasta dos prints (padrao: logs/rpa do datalake)")
    args = ap.parse_args(argv)

    carregar_env()
    try:
        cfg = ler_config(achar_config(args.config))
        url = args.url or cfg["url"]
        if args.gravar:
            return gravar(url)
        usuario, senha, alvo = credenciais(args.alvo)
    except FalhaRPA as e:
        print(f"  ERRO: {e}")
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ERRO: falta o Playwright. Rode:  python -m pip install playwright")
        return 1

    saida = Path(args.saida) if args.saida else LAKE / "logs" / "rpa"
    saida.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    timeout_ms = int(cfg["timeout_s"]) * 1000

    with sync_playwright() as pw:
        try:
            browser = abrir_navegador(pw, cfg["navegador"], args.visivel or args.pausar)
        except Exception as e:
            print(f"  ERRO: nao consegui abrir o navegador: {str(e).splitlines()[0]}")
            print("  Instale o Microsoft Edge, ou rode:  python -m playwright install chromium")
            return 1
        page = browser.new_context(locale="pt-BR").new_page()
        page.set_default_timeout(timeout_ms)
        codigo = 0
        try:
            print(f"  abrindo {url}")
            page.goto(url, wait_until="domcontentloaded")
            esperar_tela(page, timeout_ms)
            fazer_login(page, cfg, usuario, senha, timeout_ms)
            entrar_no_usuario(page, cfg, alvo, timeout_ms)
            page.screenshot(path=str(saida / f"portal_vw_{carimbo}_ok.png"), full_page=True)
            print(f"  PRONTO. Print em {saida / f'portal_vw_{carimbo}_ok.png'}")
        except Exception as e:
            codigo = 1
            msg = str(e) if isinstance(e, FalhaRPA) else f"{type(e).__name__}: {str(e).splitlines()[0]}"
            print(f"  ERRO: {msg}")
            try:
                page.screenshot(path=str(saida / f"portal_vw_{carimbo}_erro.png"), full_page=True)
                (saida / f"portal_vw_{carimbo}_erro.html").write_text(page.content(), encoding="utf-8")
                print(f"  Print e HTML da tela do erro em {saida}")
            except Exception:
                pass
        if args.pausar:
            page.pause()
        browser.close()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
