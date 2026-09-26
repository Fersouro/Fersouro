# -*- coding: utf-8 -*-
"""
BRAVOS: consulta das Notas Fiscais de uma SG (campo "Nro O.S"). SO LEITURA.

    python bravos_nf.py 210238                 # uma SG
    python bravos_nf.py 210238 214074 214397   # varias SGs
    python bravos_nf.py 210238 --data-final 25/09/2026
    python bravos_nf.py 210238 --sem-janela

Fluxo (procedimento do setor de Garantia):
  login -> Relatorios -> Relatorios -> Faturamento -> Relatorio de Notas Fiscais
  -> Periodo de selecao: DUPLO CLIQUE na data final e atualiza a data
  -> Gerar (icone de raio) -> aguarda -> Nro O.S = SG -> pesquisa -> NFs + valores

Senha: Gerenciador de Credenciais do Windows (CADASTRAR-SENHA.bat). Nunca e
impressa, gravada em arquivo, log ou print. Nao ha print da tela de login.
Saida: saida/consultas.csv e saida/historico.jsonl (acumula as consultas).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import cofre

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "saida"
MENU = [p.strip() for p in os.environ.get(
    "BRAVOS_MENU", "Relatórios;Relatórios;Faturamento;Relatório de Notas Fiscais").split(";") if p.strip()]
TIMEOUT = 60              # por etapa
TIMEOUT_RELATORIO = 300   # geracao do relatorio pode demorar


def log(msg: str) -> None:
    linha = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(linha, flush=True)
    SAIDA.mkdir(exist_ok=True)
    with open(SAIDA / "rpa.log", "a", encoding="utf-8") as f:
        f.write(f"{dt.date.today()} {linha}\n")


def sem_acento(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


class Falha(Exception):
    """Etapa que nao deu certo -- com mensagem para o operador (sem segredo)."""


# JS: acha elemento visivel cujo texto PROPRIO e exatamente o procurado,
# ignorando os ja clicados (o menu tem "Relatorios" duas vezes).
JS_ACHAR_TEXTO = r"""([alvo, ordem]) => {
  const norm = s => (s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/\s+/g,' ').trim().toLowerCase();
  const vis = e => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  // ignora icones/simbolos nas pontas (ex.: o raio do botao Gerar)
  const lim = s => norm(s).replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, '');
  const t = lim(alvo); const cands = [];
  for (const e of document.querySelectorAll('a,button,span,div,li,td,label,input[type=button],input[type=submit]')) {
    if (e.closest('[data-rpa-clicado]') === e) continue;
    const proprio = e.tagName === 'INPUT' ? e.value : [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
    const tudo = e.innerText || '';
    if ((lim(proprio) === t || (lim(tudo) === t && e.children.length <= 2)) && vis(e)) cands.push(e);
  }
  // so o elemento mais interno (o link, nao a linha <li> que o contem)
  const internos = cands.filter(c => !cands.some(o => o !== c && c.contains(o)));
  if (!internos.length) return false;
  const e = ordem === 'ultimo' ? internos[internos.length - 1] : internos[0];
  document.querySelectorAll('[data-rpa-alvo]').forEach(x => x.removeAttribute('data-rpa-alvo'));
  e.setAttribute('data-rpa-alvo', '1');
  return true; }"""

# JS: campo de entrada mais perto de um rotulo (ex.: "Nro O.S", "Data final")
JS_CAMPO_DO_ROTULO = r"""([rotulo, marca]) => {
  const rx = new RegExp(rotulo, 'i');
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const inputs = [...document.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]), textarea')].filter(vis);
  // 1) <label for> / aria-label / placeholder / title / name
  for (const i of inputs) {
    const lab = (i.labels && i.labels[0] && i.labels[0].innerText) || '';
    if (rx.test(lab) || rx.test(i.getAttribute('aria-label')||'') || rx.test(i.placeholder||'') || rx.test(i.title||'')) {
      i.setAttribute(marca, '1'); return true; } }
  // 2) texto do rotulo na tela -> input mais proximo a direita/abaixo
  // rotulos = pedacos de TEXTO na tela (inclusive texto solto, sem etiqueta)
  const rots = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const t = n.textContent.replace(/\s+/g, ' ').trim();
    if (!t || t.length > 60 || !rx.test(t)) continue;
    const rg = document.createRange(); rg.selectNodeContents(n);
    const rc = rg.getBoundingClientRect(); if (rc.width > 0) rots.push(rc); }
  let melhor = null, nota = 1e9;
  for (const a of rots) {
    for (const i of inputs) { const b = i.getBoundingClientRect();
      const dx = b.left - a.right, dy = b.top - a.top;
      if (dx < -40 || dy < -10) continue;           // so a direita ou abaixo
      const d = Math.hypot(Math.max(dx, 0), dy * 2);
      if (d < nota) { nota = d; melhor = i; } } }
  if (melhor && nota < 400) { melhor.setAttribute(marca, '1'); return true; }
  return false; }"""

# JS: tabelas visiveis (cabecalho + linhas, texto exatamente como na tela)
JS_TABELAS = r"""() => { const tx = e => (e.innerText||'').replace(/\s+/g,' ').trim(); const out = [];
  document.querySelectorAll('table').forEach(t => { const rows = [...t.rows]; if (rows.length < 1) return;
    let h = rows.findIndex(r => r.querySelector('th')); if (h < 0) h = 0;
    out.push({cab: [...rows[h].cells].map(tx), linhas: rows.slice(h + 1).map(r => [...r.cells].map(tx))}); });
  return out; }"""


class Bravos:
    def __init__(self, pw, url: str, visivel: bool):
        self.url = url
        opcoes = dict(user_data_dir=str(AQUI / "perfil"), headless=not visivel, locale="pt-BR")
        try:
            self.ctx = pw.chromium.launch_persistent_context(
                channel="msedge", ignore_default_args=["--no-sandbox"], **opcoes)
        except Exception:
            exe = os.environ.get("CHROMIUM_EXE")
            self.ctx = pw.chromium.launch_persistent_context(**opcoes, **({"executable_path": exe} if exe else {}))
        self.ctx.set_default_timeout(TIMEOUT * 1000)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.logado = False

    # ------------------------------------------------------------ utilidades
    def pausa(self, s: float) -> None:
        vivas = [p for p in self.ctx.pages if not p.is_closed()]
        (vivas[-1] if vivas else self.page).wait_for_timeout(int(s * 1000))

    def frames(self):
        for page in reversed([p for p in self.ctx.pages if not p.is_closed()]):
            for fr in page.frames:
                yield page, fr

    def esperar(self, cond, prazo: float, passo: float = 0.5):
        fim = time.monotonic() + prazo
        while time.monotonic() < fim:
            r = cond()
            if r:
                return r
            self.pausa(passo)
        return None

    def por_js(self, js: str, arg, marca: str):
        """Roda o JS em cada frame; devolve (frame, locator) do elemento marcado."""
        for page, fr in self.frames():
            try:
                if fr.evaluate(js, arg):
                    self.page = page
                    return fr, fr.locator(f"[{marca}='1']").first
            except Exception:
                continue
        return None

    def print(self, nome: str) -> None:
        if not self.logado:
            return  # nunca fotografa a tela de login
        try:
            self.page.screenshot(path=str(SAIDA / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{nome}.png"), full_page=True)
        except Exception:
            pass

    def campo_senha(self):
        for _, fr in self.frames():
            try:
                loc = fr.locator("input[type=password]")
                for i in range(loc.count()):
                    if loc.nth(i).is_visible():
                        return fr, loc.nth(i)
            except Exception:
                continue
        return None, None

    def menu_visivel(self) -> bool:
        return bool(self.por_js(JS_ACHAR_TEXTO, [MENU[0], "primeiro"], "data-rpa-alvo"))

    # ----------------------------------------------------------------- login
    def login(self, usuario: str, senha: str) -> None:
        log("Etapa 1 - login")
        if self.page.url in ("", "about:blank"):
            self.page.goto(self.url, wait_until="domcontentloaded")
        self.pausa(2)
        fr, s_el = self.campo_senha()
        if s_el is None:
            if self.menu_visivel():
                self.logado = True
                log("  ja estava logado (sessao guardada)")
                return
            raise Falha("nao achei a tela de login nem o menu principal")
        ok = fr.evaluate("""() => {
            const vis = e => !!(e.offsetWidth || e.offsetHeight);
            const ins = [...document.querySelectorAll('input')].filter(vis);
            const s = ins.find(e => e.type === 'password'); const rs = s.getBoundingClientRect();
            let m = null, n = 1e9;
            for (const e of ins) { if (!['text','email',''].includes((e.type||'text').toLowerCase())) continue;
              const r = e.getBoundingClientRect(); const d = Math.hypot(r.left - rs.left, r.top - rs.top);
              if (d < n) { n = d; m = e; } }
            if (m) m.setAttribute('data-rpa-usuario', '1'); return !!m; }""")
        if not ok:
            raise Falha("nao achei o campo de usuario")
        fr.locator("[data-rpa-usuario='1']").first.fill(usuario)
        s_el.fill(senha)
        log("  usuario e senha preenchidos")
        botao = None
        for t in ("Entrar", "Login", "Acessar", "OK", "Logar"):
            b = fr.get_by_role("button", name=re.compile(rf"^\s*{t}\s*$", re.I))
            if b.count() and b.first.is_visible():
                botao = b.first
                break
        (botao.click() if botao else s_el.press("Enter"))
        # login so vale se o MENU aparecer e o campo de senha sumir; para cedo se vier aviso de erro
        rx_erro = re.compile(r"[^\n]*(inv[aá]lid|incorret|bloquead|expirad|negad|n[aã]o autorizad)[^\n]*", re.I)

        def estado():
            if self.campo_senha()[1] is None and self.menu_visivel():
                return ("ok", "")
            for _, f in self.frames():
                try:
                    m = rx_erro.search(f.evaluate("() => document.body ? document.body.innerText : ''"))
                except Exception:
                    m = None
                if m:
                    return ("erro", m.group(0).strip()[:150])
            return None

        r = self.esperar(estado, TIMEOUT)
        if not r or r[0] != "ok":
            raise Falha("falha de autenticacao" + (f': "{r[1]}"' if r else " (a tela nao mudou)")
                        + " -- nao vou tentar de novo")
        self.logado = True
        log("  login OK (menu principal carregado)")

    # --------------------------------------------------------------- navegar
    def navegar(self) -> None:
        log("Etapa 2 - navegacao: " + " > ".join(MENU))
        for _, fr in self.frames():  # limpa marcas de navegacoes anteriores
            try:
                fr.evaluate("() => document.querySelectorAll('[data-rpa-clicado]').forEach(e => e.removeAttribute('data-rpa-clicado'))")
            except Exception:
                pass
        for i, passo in enumerate(MENU):
            ordem = "ultimo" if passo in MENU[:i] else "primeiro"  # 2o "Relatorios" = o do submenu
            achado = self.esperar(lambda: self.por_js(JS_ACHAR_TEXTO, [passo, ordem], "data-rpa-alvo"), TIMEOUT)
            if not achado:
                self.print("erro_menu")
                raise Falha(f"nao achei '{passo}' no menu")
            fr, el = achado
            try:
                el.hover(timeout=2000)
            except Exception:
                pass
            el.evaluate("e => e.setAttribute('data-rpa-clicado', '1')")
            el.click()
            log(f"  clicou: {passo}")
            self.pausa(1)
        if not self.esperar(lambda: self.por_js(JS_CAMPO_DO_ROTULO, [r"data\s*final|per[ií]odo", "data-rpa-x"], "data-rpa-x"),
                            TIMEOUT):
            self.print("erro_relatorio")
            raise Falha("o Relatorio de Notas Fiscais nao abriu (sem campos de periodo)")
        log("  Relatorio de Notas Fiscais aberto")

    # --------------------------------------------------------------- periodo
    def data_final(self, data: str) -> None:
        log(f"Etapa 3 - data final = {data}")
        achado = self.por_js(JS_CAMPO_DO_ROTULO, [r"data\s*final|at[eé]|fim|final", "data-rpa-df"], "data-rpa-df")
        if not achado:
            # sem rotulo proprio: segunda data da secao "Periodo de selecao"
            for _, fr in self.frames():
                try:
                    if fr.evaluate(r"""() => {
                        const sec = [...document.querySelectorAll('fieldset,div,table,section')].find(e =>
                            /per[ií]odo de sele[cç][aã]o/i.test(e.innerText||'') && (e.innerText||'').length < 600);
                        if (!sec) return false;
                        const ds = [...sec.querySelectorAll('input')].filter(i =>
                            /\d{2}\/\d{2}\/\d{4}/.test(i.value||'') || /date/i.test(i.type));
                        if (ds.length < 2) return false;
                        ds[ds.length - 1].setAttribute('data-rpa-df', '1'); return true; }"""):
                        achado = (fr, fr.locator("[data-rpa-df='1']").first)
                        break
                except Exception:
                    continue
        if not achado:
            self.print("erro_data_final")
            raise Falha("nao achei o campo de data final em 'Periodo de selecao'")
        fr, campo = achado
        campo.dblclick()                     # o DUPLO CLIQUE libera/atualiza a data
        self.pausa(0.5)
        campo.press("Control+a")
        campo.type(data, delay=40)
        campo.press("Tab")
        self.pausa(0.5)
        valor = campo.input_value()
        if re.sub(r"\D", "", valor) != re.sub(r"\D", "", data):
            self.print("erro_data_final")
            raise Falha(f"a data final nao foi atualizada (campo mostra '{valor}')")
        log(f"  data final confirmada: {valor}")

    # ---------------------------------------------------------------- gerar
    def gerar(self) -> None:
        log("Etapa 4 - Gerar")
        achado = self.por_js(JS_ACHAR_TEXTO, ["Gerar", "primeiro"], "data-rpa-alvo")
        if not achado:
            self.print("erro_gerar")
            raise Falha("nao achei o botao Gerar")
        achado[1].click()                    # um clique so; nada de clicar de novo
        log("  aguardando o relatorio (sem clicar de novo)...")
        ok = self.esperar(lambda: self.por_js(JS_CAMPO_DO_ROTULO, [r"nro\.?\s*o\.?\s*s", "data-rpa-os"], "data-rpa-os"),
                          TIMEOUT_RELATORIO, passo=1)
        if not ok:
            self.print("erro_gerar")
            raise Falha(f"o relatorio nao terminou em {TIMEOUT_RELATORIO}s (campo 'Nro O.S' nao apareceu)")
        log("  relatorio gerado (campo Nro O.S disponivel)")

    # -------------------------------------------------------------- pesquisa
    def pesquisar(self, sg: str) -> list[dict]:
        log(f"Etapa 5/6 - pesquisar SG {sg} no campo Nro O.S")
        achado = self.por_js(JS_CAMPO_DO_ROTULO, [r"nro\.?\s*o\.?\s*s", "data-rpa-os"], "data-rpa-os")
        if not achado:
            raise Falha("campo Nro O.S nao encontrado")
        fr, campo = achado
        campo.fill("")
        campo.fill(sg)
        if campo.input_value().strip() != sg:
            raise Falha(f"o campo Nro O.S ficou com '{campo.input_value()}', esperado '{sg}'")
        botao = None
        for t in ("Pesquisar", "Filtrar", "Buscar", "Consultar", "Localizar"):
            b = fr.get_by_role("button", name=re.compile(rf"^\s*{t}\s*$", re.I))
            if b.count() and b.first.is_visible():
                botao = b.first
                break
        (botao.click() if botao else campo.press("Enter"))
        self.pausa(2)
        # resultado() devolve None enquanto a tabela nao existe; lista (vazia ou nao) quando existe
        r = self.esperar(lambda: (lambda x: None if x is None else (x,))(self.resultado(sg)), TIMEOUT, passo=1)
        return r[0] if r else []

    def resultado(self, sg: str):
        """Linhas das tabelas que tenham coluna de NF e de valor. Valores como estao na tela."""
        achou_tabela = False
        for _, fr in self.frames():
            try:
                tabelas = fr.evaluate(JS_TABELAS)
            except Exception:
                continue
            for t in tabelas:
                cab = [sem_acento(c) for c in t["cab"]]
                i_nf = next((i for i, c in enumerate(cab) if re.search(r"\bnf\b|nota|numero|nro\.? ?nf", c)
                             and "o.s" not in c and "os" != c), None)
                i_val = next((i for i, c in enumerate(cab) if re.search(r"valor|total", c)), None)
                if i_nf is None or i_val is None:
                    continue
                achou_tabela = True
                out = []
                for l in t["linhas"]:
                    if len(l) <= max(i_nf, i_val) or not l[i_nf] or re.match(r"(?i)total", l[0] or ""):
                        continue
                    out.append({"sg": sg, "nf": l[i_nf], "valor": l[i_val],
                                "linha_completa": " | ".join(l)})
                if out:
                    return out
        return [] if achou_tabela else None

    def sessao_expirou(self) -> bool:
        return self.campo_senha()[1] is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sgs", nargs="+", help="numero(s) da SG (vai no campo Nro O.S)")
    ap.add_argument("--data-final", default=dt.date.today().strftime("%d/%m/%Y"))
    ap.add_argument("--sem-janela", action="store_true")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(AQUI / ".env")
    except ImportError:
        pass
    url = os.environ.get("BRAVOS_URL", "").strip()
    usuario = os.environ.get("BRAVOS_USUARIO", "").strip()
    if not url or not usuario:
        log("ERRO: preencha BRAVOS_URL e BRAVOS_USUARIO no arquivo .env desta pasta")
        return 1
    senha = cofre.senha(usuario)
    if not senha:
        log("ERRO: senha nao cadastrada. Rode CADASTRAR-SENHA.bat")
        return 1

    from playwright.sync_api import sync_playwright
    resultados, erros = [], []
    log(f"=== inicio: {len(a.sgs)} SG(s) ===")
    with sync_playwright() as pw:
        b = Bravos(pw, url, visivel=not a.sem_janela)
        try:
            def preparar():
                b.login(usuario, senha)
                b.navegar()
                b.data_final(a.data_final)
                b.gerar()

            preparar()
            for sg in [re.sub(r"\s", "", s) for s in a.sgs]:
                for tentativa in (1, 2):
                    try:
                        nfs = b.pesquisar(sg)
                        break
                    except Falha:
                        if tentativa == 1 and b.sessao_expirou():
                            log("  sessao expirada: novo login e volta ao relatorio")
                            b.logado = False
                            preparar()
                            continue
                        raise
                if nfs:
                    for n in nfs:
                        log(f"  SG {sg}: NF {n['nf']}  valor {n['valor']}")
                    resultados += nfs
                else:
                    log(f"  SG {sg}: Nenhuma Nota Fiscal encontrada para a SG pesquisada no periodo selecionado "
                        f"(data final {a.data_final}).")
                    resultados.append({"sg": sg, "nf": "", "valor": "", "linha_completa": "SEM NF NO PERIODO"})
        except Falha as e:
            b.print("erro")
            log(f"ERRO: {e}")
            erros.append(str(e))
        except Exception as e:
            b.print("erro")
            log(f"ERRO DE ACESSO: {type(e).__name__}: {str(e).splitlines()[0]}")
            erros.append(type(e).__name__)
        finally:
            b.ctx.close()  # encerra a sessao do navegador

    if resultados:
        SAIDA.mkdir(exist_ok=True)
        agora = dt.datetime.now().isoformat(timespec="seconds")
        arq = SAIDA / f"consulta_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(arq, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["sg", "nf", "valor", "linha_completa"], delimiter=";")
            w.writeheader()
            w.writerows(resultados)
        with open(SAIDA / "historico.jsonl", "a", encoding="utf-8") as f:
            for r in resultados:
                f.write(json.dumps({"quando": agora, "data_final": a.data_final, **r}, ensure_ascii=False) + "\n")
        log(f"resultado: {arq.name}")
    log("=== fim: " + ("OK" if not erros else "COM ERRO") + " ===")
    return 0 if not erros else 1


if __name__ == "__main__":
    sys.exit(main())
