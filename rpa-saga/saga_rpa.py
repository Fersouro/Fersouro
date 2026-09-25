# -*- coding: utf-8 -*-
"""
RPA SAGA2 - VH47 (independente do datalake).

Faz: login no Portal Rede VW -> Garantia Volkswagen -> SAGA -> SAGA2 - VH47
-> "Lista de arquivos" -> le a tabela -> salva em saida/ (CSV + print).
Com --baixar, tambem baixa os PDFs que ainda nao estao em saida/pdfs/.

SOMENTE LEITURA: so navega, le e baixa. Nao clica em botoes de envio.

Usuario e senha: arquivo .env nesta pasta (PORTAL_USUARIO, PORTAL_SENHA).
A senha nunca e impressa nem gravada em log.

    python saga_rpa.py              # le a lista
    python saga_rpa.py --baixar     # le e baixa os PDFs novos
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
URL = os.environ.get("PORTAL_URL", "https://www.portalredevw.com.br/portalredevw2/default.aspx")

# Caminho no portal: textos dos menus/links, clicados nesta ordem.
# Pode trocar no .env:  PORTAL_CAMINHO=Garantia;Garantia Volkswagen;SAGA
CAMINHO = [p.strip() for p in os.environ.get(
    "PORTAL_CAMINHO", "Garantia;Garantia Volkswagen;SAGA").split(";") if p.strip()]
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
        log("usuario e senha preenchidos (campo Login, v3)")
        antes = set(id(p) for p in self.ctx.pages)
        senha_el.press("Enter")
        self.seguir(self.page, antes)
        self.pausa(2)
        if self.campo_senha()[1] is not None:
            self.print("login_falhou")
            texto = sem_acento(self.page.inner_text("body")[:3000])
            if "captcha" in texto or "codigo" in texto or "token" in texto:
                raise Falha("o portal pediu CAPTCHA/codigo -- precisa de uma pessoa")
            raise Falha("login nao passou (a tela de senha continua) -- veja o print em saida/")
        log("login OK")

    def ir_para_lista(self) -> None:
        for passo in CAMINHO:
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
    ap.add_argument("--baixar", action="store_true", help="baixa os PDFs que ainda nao estao em saida/pdfs")
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
            log(f"lista lida: {len(itens)} arquivos, {len(meus)} do DN {dn}  -> {arq.name}")
            for i in meus[:10]:
                log("  " + " | ".join(str(i[c]) for c in cols))
            if args.baixar:
                pasta = SAIDA / "pdfs"
                pasta.mkdir(exist_ok=True)
                for i in meus:
                    nome_col = next((c for c in cols if "arquivo" in sem_acento(c) or "nome" in sem_acento(c)), cols[-1])
                    nome = re.sub(r'[<>:"/\\|?*]', "_", str(i[nome_col])) or "arquivo"
                    destino = pasta / (nome if nome.lower().endswith(".pdf") else nome + ".pdf")
                    if destino.exists():
                        continue
                    log(f"baixando {destino.name}")
                    portal.baixar(i, destino)
                    log(f"  ok ({destino.stat().st_size // 1024} KB)")
            log("=== fim: OK ===")
            return 0
        except Falha as e:
            portal.print("erro")
            log(f"ERRO: {e}")
            return 1
        finally:
            portal.ctx.close()


if __name__ == "__main__":
    sys.exit(main())
