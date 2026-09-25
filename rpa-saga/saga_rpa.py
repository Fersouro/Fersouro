# -*- coding: utf-8 -*-
"""
RPA SAGA2 - VH47 (independente do datalake).

Faz: login no Portal Rede VW -> Garantia Volkswagen -> SAGA -> SAGA2 - VH47
-> "Lista de arquivos" -> le a tabela -> salva em saida/ (CSV + print).
Com --baixar, baixa o relatorio MAIS RECENTE do DN (pela data do relatorio).
Com --baixar-todos, baixa os que faltam, do mais antigo ao mais novo.

SOMENTE LEITURA: so navega, le e baixa. Nao clica em botoes de envio.

Usuario e senha: arquivo .env nesta pasta (PORTAL_USUARIO, PORTAL_SENHA).
A senha nunca e impressa nem gravada em log.

    python saga_rpa.py              # le a lista
    python saga_rpa.py --baixar        # le e baixa o relatorio mais recente
    python saga_rpa.py --baixar-todos  # baixa os que faltam (atrasados)
    python saga_rpa.py --sem-janela # sem abrir janela do navegador
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "saida"
URL = os.environ.get("PORTAL_URL", "https://www.portalredevw.com.br/portalredevw2/Default.aspx")

# Caminho no portal: textos dos menus/links, clicados nesta ordem.
# Pode trocar no .env:  PORTAL_CAMINHO=Garantia;SAGA2
CAMINHO = [p.strip() for p in os.environ.get(
    "PORTAL_CAMINHO", "Garantia;SAGA2").split(";") if p.strip()]
# Empresa escolhida depois do login (tela de selecao de empresa/DN).
# Os dois termos podem estar em colunas diferentes da mesma linha.
EMPRESA_NOME = os.environ.get("PORTAL_EMPRESA_NOME", "TTERRASUL")
EMPRESA_DN = os.environ.get("PORTAL_EMPRESA_DN", "1079")
RELATORIO = r"SAGA\s*2\s*-?\s*VH\s*47"
LINK_LISTA = r"Lista\s+de\s+arquivos"
# Botoes que o RPA NUNCA clica (seguranca: so leitura)
PROIBIDOS = re.compile(r"enviar|transmitir|excluir|cancelar|aprovar|salvar|gravar|alterar", re.I)

TIMEOUT = 60  # segundos por etapa


def log(msg: str) -> None:
    linha = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(linha, flush=True)
    SAIDA.mkdir(exist_ok=True)
    with open(SAIDA / "rpa.log", "a", encoding="utf-8") as f:
        f.write(f"{dt.date.today()} {linha}\n")


def sem_acento(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def data_relatorio(nome: str, ano: str = "", mes: str = "") -> tuple:
    """Data do RELATORIO (nao da tela): 2026-09-22.001079_RELATORIO_VH47.pdf -> (2026, 9, 22).
    Sem data no nome, usa Ano/Mes da lista (dia 0)."""
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", nome or "")
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return int(re.sub(r"\D", "", ano) or 0), int(re.sub(r"\D", "", mes) or 0), 0
    except ValueError:
        return 0, 0, 0


class Falha(Exception):
    pass


class Portal:
    def __init__(self, pw, visivel: bool):
        self.pasta_dl = SAIDA / "tmp"
        self.pasta_dl.mkdir(parents=True, exist_ok=True)
        opcoes = dict(user_data_dir=str(AQUI / "perfil"), headless=not visivel,
                      accept_downloads=True, downloads_path=str(self.pasta_dl), locale="pt-BR")
        try:
            self.ctx = pw.chromium.launch_persistent_context(
                channel="msedge", ignore_default_args=["--no-sandbox"], **opcoes)
        except Exception:
            exe = os.environ.get("CHROMIUM_EXE")
            self.ctx = pw.chromium.launch_persistent_context(
                **opcoes, **({"executable_path": exe} if exe else {}))
        self.ctx.set_default_timeout(TIMEOUT * 1000)
        self.downloads = []
        self.ctx.on("page", lambda p: p.on("download", self._dl))
        for p in self.ctx.pages:
            p.on("download", self._dl)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def _dl(self, d):
        self.downloads.append(d)

    # -------------------------------------------------------------- utilidades
    def pausa(self, s: float) -> None:
        # espera deixando o navegador processar eventos (nova aba, download)
        vivas = [p for p in self.ctx.pages if not p.is_closed()]
        (vivas[-1] if vivas else self.page).wait_for_timeout(int(s * 1000))

    def frames(self):
        for page in reversed([p for p in self.ctx.pages if not p.is_closed()]):
            for fr in page.frames:
                yield page, fr

    def achar(self, texto: str, prazo_s: float = TIMEOUT):
        """Primeiro elemento VISIVEL com esse texto, em qualquer aba/iframe.
        Texto exato primeiro; so depois 'contem'."""
        fim = time.monotonic() + prazo_s
        exato = re.compile(rf"^\s*(?:{texto})\s*$", re.I)
        solto = re.compile(texto, re.I)
        while True:
            for rx in (exato, solto):
                for page, fr in self.frames():
                    for loc in (fr.get_by_role("link", name=rx), fr.get_by_role("menuitem", name=rx),
                                fr.get_by_role("button", name=rx), fr.get_by_text(rx)):
                        try:
                            for i in range(min(loc.count(), 10)):
                                if loc.nth(i).is_visible():
                                    return page, loc.nth(i)
                        except Exception:
                            continue
            if time.monotonic() > fim:
                return None, None
            self.pausa(0.5)

    def clicar(self, texto: str) -> None:
        page, el = self.achar(texto)
        if el is None:
            raise Falha(f"nao achei '{texto}' na tela")
        rotulo = (el.inner_text(timeout=2000) or "").strip()
        if PROIBIDOS.search(rotulo):
            raise Falha(f"bloqueado por seguranca: '{rotulo}'")
        antes = set(id(p) for p in self.ctx.pages)
        try:
            el.hover(timeout=2000)
        except Exception:
            pass
        el.click()
        self.seguir(page, antes)

    def seguir(self, page, antes) -> None:
        """Depois de um clique: se abriu aba nova, passa a trabalhar nela."""
        for _ in range(15):
            novas = [p for p in self.ctx.pages if id(p) not in antes and not p.is_closed()]
            if novas:
                self.page = novas[-1]
                log(f"abriu nova aba: {self.page.url}")
                break
            self.pausa(0.2)
        else:
            self.page = page
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT * 1000)
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

    def print(self, nome: str) -> Path:
        arq = SAIDA / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{nome}.png"
        try:
            self.page.screenshot(path=str(arq), full_page=True)
        except Exception:
            pass
        return arq

    # ------------------------------------------------------------------ etapas
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

    def login(self, usuario: str, senha: str) -> None:
        log(f"abrindo {URL}")
        self.page.goto(URL, wait_until="domcontentloaded")
        self.pausa(2)
        fr, senha_el = self.campo_senha()
        if senha_el is None:
            log("sem tela de login: ja estava logado (sessao guardada)")
            return
        # Usuario = o campo de texto IMEDIATAMENTE antes da senha, no mesmo
        # formulario/caixa (a pagina tem outros campos, ex.: busca do Suporte).
        marcou = fr.evaluate("""() => {
            // Campo de usuario = o campo de texto MAIS PERTO da senha na tela
            // (no Portal Rede, a caixa "Login" fica colada na senha; a busca
            // do "Suporte" fica acima). Nome com login/usuario/cpf ganha bonus.
            const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
            const inputs = [...document.querySelectorAll('input')].filter(vis);
            const senha = inputs.find(e => e.type === 'password');
            if (!senha) return false;
            const rs = senha.getBoundingClientRect();
            let melhor = null, nota = 1e9;
            for (const e of inputs) {
                const t = (e.type || 'text').toLowerCase();
                if (!['text', 'email', 'tel', 'number'].includes(t)) continue;
                const r = e.getBoundingClientRect();
                let d = Math.hypot((r.left + r.right) / 2 - (rs.left + rs.right) / 2,
                                   (r.top + r.bottom) / 2 - (rs.top + rs.bottom) / 2);
                const nome = ((e.name || '') + ' ' + (e.id || '')).toLowerCase();
                if (/login|usu|user|cpf/.test(nome)) d -= 300;
                if (/busca|search|pesq|suporte/.test(nome)) d += 1000;
                if (senha.form && e.form === senha.form) d -= 100;
                if (d < nota) { nota = d; melhor = e; }
            }
            if (!melhor) return false;
            melhor.setAttribute('data-rpa-usuario', '1');
            return true; }""")
        if not marcou:
            self.print("login_nao_encontrado")
            raise Falha("nao achei o campo de usuario ao lado da senha")
        fr.locator("[data-rpa-usuario='1']").first.fill(usuario)
        senha_el.fill(senha)
        log("usuario e senha preenchidos (campo Login, v4)")
        antes = set(id(p) for p in self.ctx.pages)
        url_antes = self.page.url
        # Botao "ok" ao lado da senha (o Portal Rede nao envia com Enter).
        achou_botao = fr.evaluate("""() => {
            const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
            const senha = [...document.querySelectorAll('input[type=password]')].find(vis);
            if (!senha) return false;
            const rs = senha.getBoundingClientRect();
            const txt = e => (e.value || e.innerText || e.alt || e.title || '').trim();
            let melhor = null, nota = 1e9;
            for (const e of document.querySelectorAll(
                    'input[type=submit], input[type=image], input[type=button], button, a, img[onclick]')) {
                if (!vis(e)) continue;
                const r = e.getBoundingClientRect();
                let d = Math.hypot(r.left - rs.right, (r.top + r.bottom - rs.top - rs.bottom) / 2);
                if (/^(ok|entrar|acessar|login|logar|ir)$/i.test(txt(e))) d -= 150;
                if (d < nota) { nota = d; melhor = e; }
            }
            if (!melhor || nota > 250) return false;
            melhor.setAttribute('data-rpa-ok', '1');
            return true; }""")
        if achou_botao:
            fr.locator("[data-rpa-ok='1']").first.click()
            log("clicou no botao ok do login")
        else:
            senha_el.press("Enter")
            log("sem botao ok visivel: enviou com Enter")
        # espera a tela mudar: some o campo de senha, muda a URL ou abre aba
        fim = time.monotonic() + TIMEOUT
        while time.monotonic() < fim:
            self.pausa(1)
            novas = [p for p in self.ctx.pages if id(p) not in antes and not p.is_closed()]
            if novas:
                self.page = novas[-1]
                break
            if self.page.url != url_antes or self.campo_senha()[1] is None or self.tela_empresa():
                break
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        self.pausa(2)
        # A caixa de Login continua no topo mesmo depois de entrar; o que prova
        # o login e a tela "Escolhendo a empresa" (ou o campo de senha sumir).
        if self.campo_senha()[1] is not None and self.page.url == url_antes and not self.tela_empresa():
            self.print("login_falhou")
            self.salvar_html("login_falhou")
            texto = ""
            for _, f in self.frames():
                try:
                    texto += " " + sem_acento(f.evaluate("() => document.documentElement.innerText || ''")[:3000])
                except Exception:
                    pass
            if "captcha" in texto or "codigo de verificacao" in texto or "token" in texto:
                raise Falha("o portal pediu CAPTCHA/codigo -- precisa de uma pessoa")
            if "invalid" in texto or "incorret" in texto or "bloquead" in texto:
                raise Falha("o portal recusou o login (usuario/senha invalidos ou conta bloqueada) -- veja o print")
            raise Falha("login nao passou (a tela nao mudou) -- veja login_falhou.png em saida/")
        log("login OK")

    def tela_empresa(self) -> bool:
        """Esta na tela 'Escolhendo a empresa' (ou ha uma opcao com o DN)?"""
        for _, fr in self.frames():
            try:
                if fr.evaluate("""(dn) => {
                    const t = (document.body && document.body.innerText) || '';
                    if (/escolhendo a empresa/i.test(t)) return true;
                    const r = new RegExp('\\(0*' + dn + '\\)');
                    return [...document.querySelectorAll('input[type=radio], option')].some(e => {
                        const l = e.labels && e.labels[0] ? e.labels[0].innerText : (e.text || '');
                        const viz = (e.parentElement && e.parentElement.innerText) || '';
                        return r.test(l) || r.test(viz); }); }""", EMPRESA_DN):
                    return True
            except Exception:
                continue
        return False

    def escolher_empresa(self) -> None:
        """Tela de escolha de empresa: marca a linha/opcao que tem TTERRASUL e
        1079 (podem estar em colunas diferentes) e confirma. Se a tela nao
        aparecer, segue."""
        js = r"""([nome, dn]) => {
          const rN = new RegExp(nome, 'i'), rD = new RegExp('(^|[^0-9])0*' + dn + '([^0-9]|$)');
          const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
          const tx = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ');
          // 1) lista suspensa
          for (const sel of document.querySelectorAll('select')) {
            if (!vis(sel)) continue;
            for (const o of sel.options) if (rN.test(o.text) && rD.test(o.text)) {
              sel.value = o.value; sel.dispatchEvent(new Event('change', {bubbles: true}));
              return {como: 'lista', texto: o.text.trim()}; } }
          // 2) menor bloco (linha de tabela, item, label) com os dois termos
          let alvo = null;
          for (const e of document.querySelectorAll('tr, li, label, div, span, a, td')) {
            if (!vis(e)) continue; const t = tx(e);
            if (rN.test(t) && rD.test(t) && t.length < 300) {
              if (!alvo || e.contains(alvo) === false && alvo.contains(e)) alvo = e;
              else if (!alvo.contains(e) && t.length < tx(alvo).length) alvo = e; } }
          if (!alvo) return null;
          const marca = alvo.querySelector('input[type=radio], input[type=checkbox]')
                     || (alvo.closest('tr') || alvo).querySelector('input[type=radio], input[type=checkbox]');
          if (marca) { marca.setAttribute('data-rpa-emp', '1');
                       return {como: 'marcar', texto: tx(alvo).trim()}; }
          const clic = alvo.querySelector('a, button, input[type=button], input[type=submit]') || alvo;
          clic.setAttribute('data-rpa-emp', '1');
          return {como: 'clicar', texto: tx(alvo).trim()}; }"""
        fim = time.monotonic() + 20
        while time.monotonic() < fim:
            for page, fr in self.frames():
                r = None
                # 1a tentativa: nome + DN; 2a: so o DN (tela que mostra so o numero)
                for nome in (EMPRESA_NOME, ""):
                    try:
                        r = fr.evaluate(js, [nome, EMPRESA_DN])
                    except Exception:
                        r = None
                    if r:
                        break
                if not r:
                    continue
                log(f"empresa encontrada ({r['como']}): {r['texto'][:120]}")
                antes = set(id(p) for p in self.ctx.pages)
                if r["como"] != "lista":
                    el = fr.locator("[data-rpa-emp='1']").first
                    # clique simples: marcar o radio ja recarrega a pagina no
                    # portal (postback), entao nao da para "conferir" a marca.
                    el.click(force=True, no_wait_after=True)
                    log("DN marcado")
                    self.pausa(1)
                # botao de confirmar, se existir
                for b in ("OK", "Confirmar", "Acessar", "Entrar", "Continuar", "Selecionar", "Avançar", "Prosseguir"):
                    bt = fr.locator(f"input[type=submit][value='{b}' i], input[type=button][value='{b}' i]").or_(
                        fr.get_by_role("button", name=re.compile(rf"^\s*{b}\s*$", re.I)))
                    try:
                        if bt.count() and bt.first.is_visible():
                            bt.first.click()
                            log(f"confirmado ({b})")
                            break
                    except Exception:
                        continue
                self.seguir(page, antes)
                return
            self.pausa(0.5)
        log(f"nao apareceu escolha de empresa com {EMPRESA_NOME} + {EMPRESA_DN} (seguindo)")

    def salvar_html(self, nome: str) -> None:
        """HTML da tela (todas as abas/frames) para diagnostico. Sem senha:
        o valor digitado num campo de senha nao fica no HTML."""
        partes = []
        for page, fr in self.frames():
            try:
                partes.append(f"<!-- {page.url} | frame {fr.url} -->\n{fr.content()}")
            except Exception:
                pass
        (SAIDA / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{nome}.html").write_text("\n".join(partes), encoding="utf-8")

    def ir_para_lista(self) -> None:
        for i, passo in enumerate(CAMINHO):
            proximo = CAMINHO[i + 1] if i + 1 < len(CAMINHO) else None
            if proximo:
                # menu suspenso: passar o mouse costuma abrir o submenu;
                # so clica se o proximo item nao aparecer.
                page, el = self.achar(passo)
                if el is None:
                    self.print("erro_menu")
                    raise Falha(f"nao achei '{passo}' na tela")
                el.hover()
                self.pausa(1)
                if self.achar(proximo, 3)[1] is not None:
                    log(f"mouse sobre: {passo}")
                    continue
            log(f"clicando em: {passo}")
            self.clicar(passo)
        log('procurando "Lista de arquivos" do SAGA2 - VH47')
        js = r"""([rel, lnk]) => {
          const rR=new RegExp(rel,'i'), rL=new RegExp(lnk,'i');
          const tx=e=>(e.innerText||e.textContent||e.value||e.title||'').replace(/\s+/g,' ').trim();
          document.querySelectorAll('[data-rpa]').forEach(e=>e.removeAttribute('data-rpa'));
          const links=[...document.querySelectorAll('a,button,input[type=button],input[type=submit]')].filter(a=>rL.test(tx(a)));
          let melhor=null, prof=1e9;
          for (const a of links){ let e=a,p=0; while(e&&e!==document.body){ if(rR.test(tx(e))){
              const n=[...e.querySelectorAll('a,button,input')].filter(x=>rL.test(tx(x))).length;
              if((n<=1||e===a)&&p<prof){melhor=a;prof=p;} break;} e=e.parentElement;p++; } }
          if(!melhor){
            // Tela real: titulos e links soltos, um embaixo do outro. Pega o
            // primeiro link "Lista de Arquivos" DEPOIS do titulo "Saga2 - VH47"
            // e antes do proximo titulo "Saga2 - ...".
            const w=document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
            let depois=false, n;
            while((n=w.nextNode())){
              if(n.nodeType===3){ const t=n.textContent.replace(/\s+/g,' ').trim();
                if(!t) continue;
                if(rR.test(t)){ depois=true; continue; }
                if(depois && /saga\s*2\s*-/i.test(t) && !rL.test(t)) break; }
              else if(depois && links.includes(n)){ melhor=n; break; } } }
          if(melhor){melhor.setAttribute('data-rpa','1');return true;} return false; }"""
        fim = time.monotonic() + TIMEOUT
        while time.monotonic() < fim:
            for page, fr in self.frames():
                try:
                    if fr.evaluate(js, [RELATORIO, LINK_LISTA]):
                        antes = set(id(p) for p in self.ctx.pages)
                        fr.locator("[data-rpa='1']").first.click()
                        self.seguir(page, antes)
                        log("Lista de arquivos aberta")
                        return
                except Exception:
                    continue
            self.pausa(0.5)
        self.print("lista_nao_encontrada")
        raise Falha('nao achei o link "Lista de arquivos" do SAGA2 - VH47')

    def ler_lista(self) -> list[dict]:
        js = r"""() => { const tx=e=>(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim(); const out=[];
          document.querySelectorAll('table').forEach((t,ti)=>{ t.setAttribute('data-rpa-t',ti); const rows=[...t.rows]; if(rows.length<2) return;
            let h=rows.findIndex(r=>r.querySelector('th')); if(h<0) h=0; const cab=[...rows[h].cells].map(tx);
            rows.slice(h+1).forEach((r,ri)=>{ r.setAttribute('data-rpa-l',ri); out.push({t:ti,l:ri,cab,cel:[...r.cells].map(tx)}); }); });
          return out; }"""
        fim = time.monotonic() + TIMEOUT
        while time.monotonic() < fim:
            for page, fr in self.frames():
                try:
                    linhas = fr.evaluate(js)
                except Exception:
                    continue
                itens = []
                for ln in linhas:
                    cab = [sem_acento(c) for c in ln["cab"]]
                    if not any("ano" == c for c in cab) or not any("dn" == c for c in cab):
                        continue
                    reg = {ln["cab"][i]: (ln["cel"][i] if i < len(ln["cel"]) else "") for i in range(len(cab))}
                    reg["_frame"], reg["_t"], reg["_l"] = fr, ln["t"], ln["l"]
                    itens.append(reg)
                if itens:
                    self.page = page
                    return itens
            self.pausa(0.5)
        self.print("tabela_nao_encontrada")
        raise Falha("a pagina abriu mas nao achei a tabela (Ano / Mes / DN / Nome do arquivo)")

    def baixar(self, item: dict, destino: Path) -> Path:
        linha = item["_frame"].locator(f"table[data-rpa-t='{item['_t']}'] tr[data-rpa-l='{item['_l']}']").first
        link = linha.locator("a").first
        n = len(self.downloads)
        antes = set(id(p) for p in self.ctx.pages)
        link.click()
        fim = time.monotonic() + 120
        while time.monotonic() < fim:
            if len(self.downloads) > n:
                parcial = destino.with_suffix(".parcial")
                self.downloads[n].save_as(str(parcial))  # espera terminar
                break
            novas = [p for p in self.ctx.pages if id(p) not in antes and not p.is_closed()]
            if novas and ".pdf" in novas[-1].url.lower():
                parcial = destino.with_suffix(".parcial")
                parcial.write_bytes(self.ctx.request.get(novas[-1].url).body())
                novas[-1].close()
                break
            self.pausa(0.3)
        else:
            raise Falha("download nao comecou em 120s")
        dados = parcial.read_bytes()
        if not dados.startswith(b"%PDF") or b"%%EOF" not in dados[-2048:]:
            parcial.rename(destino.with_suffix(".invalido"))
            raise Falha("arquivo baixado nao e um PDF inteiro")
        parcial.rename(destino)
        return destino


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baixar", action="store_true", help="baixa o relatorio MAIS RECENTE do DN")
    ap.add_argument("--baixar-todos", action="store_true",
                    help="baixa todos os que ainda nao estao em saida/pdfs, do mais antigo ao mais novo (atrasados)")
    ap.add_argument("--sem-janela", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(AQUI / ".env")
    except ImportError:
        pass
    usuario = os.environ.get("PORTAL_USUARIO", "").strip()
    senha = os.environ.get("PORTAL_SENHA", "")
    dn = os.environ.get("DN", "1079").lstrip("0")
    if not usuario or not senha:
        log("ERRO: falta PORTAL_USUARIO ou PORTAL_SENHA no arquivo .env desta pasta")
        return 1

    from playwright.sync_api import sync_playwright

    log("=== inicio ===")
    with sync_playwright() as pw:
        portal = Portal(pw, visivel=not args.sem_janela)
        try:
            portal.login(usuario, senha)
            portal.print("tela_empresa")
            portal.salvar_html("tela_empresa")
            portal.escolher_empresa()
            portal.print("depois_do_login")
            portal.ir_para_lista()
            itens = portal.ler_lista()
            portal.print("lista")
            cols = [c for c in itens[0] if not c.startswith("_")]
            arq = SAIDA / f"lista_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
            with open(arq, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", delimiter=";")
                w.writeheader()
                w.writerows(itens)
            meus = [i for i in itens if any(re.sub(r"\D", "", str(v)).lstrip("0") == dn
                                            for k, v in i.items() if sem_acento(k) == "dn")]
            nome_col = next((c for c in cols if "arquivo" in sem_acento(c) or "nome" in sem_acento(c)), cols[-1])
            col_ano = next((c for c in cols if sem_acento(c) == "ano"), None)
            col_mes = next((c for c in cols if sem_acento(c) in ("mes", "mês")), None)

            def quando(i):
                return data_relatorio(str(i[nome_col]), str(i.get(col_ano, "")), str(i.get(col_mes, "")))

            meus.sort(key=quando, reverse=True)  # MAIS RECENTE primeiro (pela data do relatorio)
            log(f"lista lida: {len(itens)} arquivos, {len(meus)} do DN {dn}  -> {arq.name}")
            if meus:
                d = quando(meus[0])
                log(f"mais recente: {meus[0][nome_col]}  (data {d[2]:02d}/{d[1]:02d}/{d[0]})")
            for i in meus[:5]:
                log("  " + " | ".join(str(i[c]) for c in cols))

            if args.baixar or args.baixar_todos:
                pasta = SAIDA / "pdfs"
                pasta.mkdir(exist_ok=True)
                # normal: so o mais recente. --baixar-todos: os que faltam, do mais antigo ao mais novo
                fila = meus[:1] if not args.baixar_todos else list(reversed(meus))
                for i in fila:
                    nome = re.sub(r'[<>:"/\\|?*]', "_", str(i[nome_col])) or "arquivo"
                    destino = pasta / (nome if nome.lower().endswith(".pdf") else nome + ".pdf")
                    if destino.exists():
                        log(f"ja baixado antes: {destino.name}")
                        continue
                    log(f"baixando {destino.name}")
                    portal.baixar(i, destino)
                    log(f"  ok ({destino.stat().st_size // 1024} KB)")
                if list((AQUI / "planilhas").glob("*.xls")):
                    log("cruzando o relatorio MAIS RECENTE com as planilhas da pasta 'planilhas'")
                    import cruzar
                    cruzar.main([])
                else:
                    log("para cruzar com a planilha: coloque o .xls do fechamento em 'planilhas' e rode CRUZAR.bat")
            log("=== fim: OK ===")
            return 0
        except Falha as e:
            portal.print("erro")
            log(f"ERRO: {e}")
            return 1
        except Exception as e:  # rede fora, portal fora do ar, tela inesperada
            portal.print("erro")
            log(f"ERRO DE ACESSO: {type(e).__name__}: {str(e).splitlines()[0]}")
            log("(portal fora do ar ou sem internet NAO quer dizer que nao ha arquivo novo)")
            return 2
        finally:
            portal.ctx.close()


if __name__ == "__main__":
    sys.exit(main())
