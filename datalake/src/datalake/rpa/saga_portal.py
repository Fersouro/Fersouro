"""Navegador no Portal Rede VW: login, caminho ate a 'Lista de arquivos' do
SAGA2 - VH47, leitura da lista e download dos PDFs.

Principios (pedidos do negocio):
  * elemento achado por TEXTO/papel/estrutura, nunca por posicao na tela;
  * espera pelo elemento aparecer (polling com prazo), nao por sleep fixo;
  * procura em todas as abas e todos os iframes -- popup, nova aba e
    redirecionamento sao tratados como "a tela ativa agora e aquela";
  * download so conta quando o arquivo final existe e e um PDF inteiro.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .controle import ItemLista
from .pdf_extrator import ErroExtracao, validar_pdf
from .valores import chave_numerica, normalizar_texto

log = logging.getLogger("rpa.portal")

MESES = {
    "jan": 1, "janeiro": 1, "fev": 2, "fevereiro": 2, "mar": 3, "marco": 3, "abr": 4, "abril": 4,
    "mai": 5, "maio": 5, "jun": 6, "junho": 6, "jul": 7, "julho": 7, "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9, "out": 10, "outubro": 10, "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}


class ErroPortal(Exception):
    """Passo de navegacao que nao deu certo (mensagem para o operador)."""


@dataclass
class ConfigPortal:
    url: str
    navegador: str = "msedge"
    perfil_dir: Path | None = None
    headless: bool = False
    timeout_s: int = 60
    espera_login_min: int = 10
    logado_quando: list[str] = field(default_factory=lambda: ["GARANTIA VOLKSWAGEN"])
    caminho: list[str] = field(default_factory=lambda: ["GARANTIA VOLKSWAGEN", "SAGA"])
    relatorio: str = r"SAGA\s*2\s*-?\s*VH\s*47"
    link_lista: str = r"Lista\s+de\s+arquivos"
    colunas: dict[str, list[str]] = field(default_factory=dict)
    timeout_download_s: int = 120

    @classmethod
    def from_dict(cls, d: dict[str, Any], lista: dict[str, Any], base: Path) -> "ConfigPortal":
        perfil = d.get("perfil_dir")
        colunas = {k: ([v] if isinstance(v, str) else list(v)) for k, v in (lista.get("colunas") or {}).items()}
        faltam = {"ano", "mes", "dn", "nome"} - set(colunas)
        if faltam:
            raise ErroPortal(f"lista.colunas precisa de: {', '.join(sorted(faltam))}")
        return cls(
            url=d["url"],
            navegador=d.get("navegador", "msedge"),
            perfil_dir=Path(perfil) if perfil else base / "perfil_navegador",
            headless=bool(d.get("headless", False)),
            timeout_s=int(d.get("timeout_s", 60)),
            espera_login_min=int(d.get("espera_login_min", 10)),
            logado_quando=list(d.get("logado_quando") or ["GARANTIA VOLKSWAGEN"]),
            caminho=list(d.get("caminho") or []),
            relatorio=d.get("relatorio", cls.relatorio),
            link_lista=d.get("link_lista", cls.link_lista),
            colunas=colunas,
            timeout_download_s=int(d.get("timeout_download_s", 120)),
        )


# ------------------------------------------------------------------ utilitarios

def parse_mes(texto: Any) -> int:
    """'09', '9', 'Setembro', 'SET', 'set/2025', '2025-09' -> 9."""
    t = normalizar_texto(str(texto or ""))
    m = re.search(r"[a-z]+", t)
    if m and m.group(0) in MESES:
        return MESES[m.group(0)]
    numeros = re.findall(r"\d+", t)
    for n in numeros:
        if len(n) <= 2 and 1 <= int(n) <= 12:
            return int(n)
    raise ValueError(f"mes nao reconhecido: {texto!r}")


def parse_ano(texto: Any) -> int:
    m = re.search(r"(19|20)\d{2}", str(texto or ""))
    if not m:
        raise ValueError(f"ano nao reconhecido: {texto!r}")
    return int(m.group(0))


def _compacto(texto: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", normalizar_texto(str(texto or "")))


def nome_seguro(nome: str) -> str:
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", nome).strip(" .") or "arquivo"
    return limpo if limpo.lower().endswith(".pdf") else limpo + ".pdf"


def mapear_colunas(cabecalhos: list[str], apelidos: dict[str, list[str]]) -> dict[str, int]:
    """Cabecalhos da tabela -> {campo: indice}. Casa sem acento/pontuacao."""
    comp = [_compacto(c) for c in cabecalhos]
    mapa: dict[str, int] = {}
    for campo, nomes in apelidos.items():
        alvos = [_compacto(n) for n in nomes]
        for alvo in alvos:  # apelido na ordem de preferencia; igualdade antes de "contem"
            if alvo in comp:
                mapa[campo] = comp.index(alvo)
                break
        else:
            for i, c in enumerate(comp):
                if any(a and a in c for a in alvos) and i not in mapa.values():
                    mapa[campo] = i
                    break
    return mapa


def itens_da_tabela(tabela: dict[str, Any], apelidos: dict[str, list[str]]) -> list[ItemLista]:
    """Converte uma tabela lida do DOM em itens. Linhas sem ano/mes validos sao ignoradas."""
    mapa = mapear_colunas(tabela["cabecalhos"], apelidos)
    if not {"ano", "mes", "dn", "nome"} <= set(mapa):
        return []
    itens = []
    for linha in tabela["linhas"]:
        celulas = linha["celulas"]
        try:
            def cel(campo: str, celulas: list[str] = celulas) -> str:
                i = mapa.get(campo)
                return celulas[i].strip() if i is not None and i < len(celulas) else ""

            nome = cel("nome")
            if not nome:
                continue
            itens.append(ItemLista(
                ano=parse_ano(cel("ano")), mes=parse_mes(cel("mes")),
                regional=cel("regional"), dn=chave_numerica(cel("dn")) or cel("dn"),
                nome=nome, indice=linha["indice"],
            ))
        except ValueError as exc:
            log.debug("linha ignorada (%s): %s", exc, celulas)
    return itens


# JS: le todas as tabelas do frame, marcando cada <table>/<tr> para achar de novo.
_JS_TABELAS = r"""
() => {
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const out = [];
  document.querySelectorAll('table').forEach((t, ti) => {
    t.setAttribute('data-rpa-tabela', String(ti));
    const rows = Array.from(t.rows);
    if (rows.length < 2) return;
    let h = rows.findIndex(r => r.querySelector('th'));
    if (h < 0) h = 0;
    const cab = Array.from(rows[h].cells).map(txt);
    const linhas = [];
    rows.slice(h + 1).forEach((r, ri) => {
      r.setAttribute('data-rpa-linha', String(ri));
      const links = r.querySelectorAll('a, button, input[type=button], input[type=submit], input[type=image]');
      linhas.push({indice: ri, celulas: Array.from(r.cells).map(txt), links: links.length});
    });
    out.push({tabela: ti, cabecalhos: cab, linhas});
  });
  return out;
}
"""

# JS: acha o link "Lista de arquivos" que pertence ao bloco do relatorio (VH47).
# Sobe do link ate o menor ancestral cujo texto cita o relatorio; esse ancestral
# precisa conter UM so link "Lista de arquivos" -- senao o link e de outro relatorio.
_JS_LINK_DO_RELATORIO = r"""
([relatorio, linkLista]) => {
  const rxRel = new RegExp(relatorio, 'i'), rxLink = new RegExp(linkLista, 'i');
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const links = Array.from(document.querySelectorAll('a, button, input[type=button], input[type=submit]'))
    .filter(a => rxLink.test(txt(a) || a.value || a.title || ''));
  document.querySelectorAll('[data-rpa-alvo]').forEach(e => e.removeAttribute('data-rpa-alvo'));
  const candidatos = [];
  links.forEach(a => {
    let el = a, prof = 0;
    while (el && el !== document.body) {
      if (rxRel.test(txt(el) || el.title || '')) {
        const dentro = Array.from(el.querySelectorAll('a, button, input')).filter(x => rxLink.test(txt(x) || x.value || x.title || ''));
        if (dentro.length <= 1 || el === a) candidatos.push({a, prof});
        break;
      }
      el = el.parentElement; prof++;
    }
  });
  if (!candidatos.length) return {achados: links.length, ok: false};
  candidatos.sort((x, y) => x.prof - y.prof);
  candidatos[0].a.setAttribute('data-rpa-alvo', '1');
  return {achados: links.length, ok: true, candidatos: candidatos.length};
}
"""


# ---------------------------------------------------------------- a sessao

class SessaoPortal:
    """Navegador com perfil persistente (o login manual fica guardado)."""

    def __init__(self, cfg: ConfigPortal, pasta_temp: Path):
        self.cfg = cfg
        self.pasta_temp = Path(pasta_temp)
        self.pasta_temp.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self.ctx = None
        self.page = None
        self._downloads: list[Any] = []

    # ----------------------------------------------------------- ciclo de vida
    def __enter__(self) -> "SessaoPortal":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        opcoes = dict(
            user_data_dir=str(self.cfg.perfil_dir), headless=self.cfg.headless,
            accept_downloads=True, downloads_path=str(self.pasta_temp), locale="pt-BR",
        )
        self.cfg.perfil_dir.mkdir(parents=True, exist_ok=True)
        tentativas = [self.cfg.navegador] if self.cfg.navegador in ("msedge", "chrome") else []
        tentativas.append(None)
        ultimo: Exception | None = None
        for canal in tentativas:
            try:
                extra = {"channel": canal} if canal else {}
                exe = os.environ.get("RPA_CHROMIUM_EXECUTAVEL")
                if exe and not canal:
                    extra["executable_path"] = exe
                self.ctx = self._pw.chromium.launch_persistent_context(**opcoes, **extra)
                break
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                log.warning("Nao abri o navegador %s: %s", canal or "chromium", str(exc).splitlines()[0])
        if self.ctx is None:
            self._pw.stop()
            raise ErroPortal(f"Nao consegui abrir o navegador: {ultimo}")
        self.ctx.set_default_timeout(self.cfg.timeout_s * 1000)
        self.ctx.on("page", self._nova_aba)
        for p in self.ctx.pages:
            self._escutar(p)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.ctx is not None:
                self.ctx.close()
        finally:
            if self._pw is not None:
                self._pw.stop()

    def _escutar(self, page) -> None:
        page.on("download", self._ao_baixar)

    def _ao_baixar(self, download) -> None:
        self._downloads.append(download)

    def _nova_aba(self, page) -> None:
        log.info("Nova aba/popup aberta: %s", page.url or "(carregando)")
        self._escutar(page)

    # ---------------------------------------------------------------- esperas
    def esperar_carregar(self, page=None) -> None:
        page = page or self.page
        for estado in ("domcontentloaded", "networkidle"):
            try:
                page.wait_for_load_state(estado, timeout=self.cfg.timeout_s * 1000 if estado == "domcontentloaded" else 8000)
            except Exception:  # noqa: BLE001 - networkidle pode nunca vir (polling)
                pass

    def _pausa(self, segundos: float) -> None:
        """Pausa que deixa o Playwright processar eventos (nova aba, download).
        time.sleep puro congela a API sincrona: a aba nova nem apareceria."""
        for p in reversed(self.ctx.pages):
            if not p.is_closed():
                p.wait_for_timeout(segundos * 1000)
                return
        time.sleep(segundos)

    def _frames(self):
        """Todas as abas (a mais nova primeiro) e todos os frames de cada uma."""
        for page in reversed(self.ctx.pages):
            if page.is_closed():
                continue
            for frame in page.frames:
                yield page, frame

    @staticmethod
    def _localizadores(frame, texto: str, solto: bool):
        """Texto exato primeiro (link/menu/botao/aba/texto); 'solto' (contem) so
        na segunda passada -- assim "SAGA" nao casa com "SAGA2 - VH47"."""
        if solto:
            rx = re.compile(texto, re.IGNORECASE)
            yield frame.get_by_role("link", name=rx)
            yield frame.get_by_text(rx)
            return
        rx = re.compile(rf"^\s*(?:{texto})\s*$", re.IGNORECASE)
        for papel in ("link", "menuitem", "button", "tab"):
            yield frame.get_by_role(papel, name=rx)
        yield frame.get_by_text(rx)

    def achar(self, texto: str, timeout_s: float | None = None):
        """(page, locator) do primeiro elemento visivel com o texto, em qualquer aba/frame."""
        prazo = time.monotonic() + (timeout_s if timeout_s is not None else self.cfg.timeout_s)
        while True:
            for solto in (False, True):
                for page, frame in self._frames():
                    for loc in self._localizadores(frame, texto, solto):
                        try:
                            n = loc.count()
                        except Exception:  # noqa: BLE001 - frame navegou no meio
                            continue
                        for i in range(min(n, 10)):
                            alvo = loc.nth(i)
                            try:
                                if alvo.is_visible():
                                    return page, alvo
                            except Exception:  # noqa: BLE001
                                continue
            if time.monotonic() >= prazo:
                return None, None
            self._pausa(0.5)

    def clicar(self, texto: str, etapa: str) -> None:
        """Clica no elemento pelo texto e segue para onde o clique levar
        (mesma aba, nova aba/popup ou iframe)."""
        page, alvo = self.achar(texto)
        if alvo is None:
            raise ErroPortal(f"Etapa '{etapa}': nao achei '{texto}' na tela (nem em iframes/abas).")
        abas_antes = set(id(p) for p in self.ctx.pages)
        try:
            alvo.hover(timeout=3000)  # menus que abrem no mouse
        except Exception:  # noqa: BLE001
            pass
        alvo.click()
        self._seguir_clique(page, abas_antes)

    def _seguir_clique(self, page, abas_antes: set[int]) -> None:
        prazo = time.monotonic() + 3
        while time.monotonic() < prazo:
            novas = [p for p in self.ctx.pages if id(p) not in abas_antes and not p.is_closed()]
            if novas:
                self.page = novas[-1]
                break
            self._pausa(0.2)
        else:
            self.page = page
        self.esperar_carregar(self.page)

    # ------------------------------------------------------------------ login
    def _logado(self, timeout_s: float) -> bool:
        return any(self.achar(t, timeout_s)[1] is not None for t in self.cfg.logado_quando)

    def garantir_login(self, login_automatico: Callable[[Any], None] | None) -> None:
        log.info("Abrindo %s", self.cfg.url)
        if not self.page.url or self.page.url == "about:blank":
            self.page.goto(self.cfg.url, wait_until="domcontentloaded")
        self.esperar_carregar()
        if self._logado(5):
            log.info("Login ja realizado (sessao guardada no perfil do navegador)")
            return
        if login_automatico is not None:
            log.info("Fazendo login com as credenciais do .env")
            try:
                login_automatico(self.page)
            except Exception as exc:  # noqa: BLE001 - FalhaRPA do rpa_portal_vw e afins
                raise ErroPortal(f"Login automatico falhou: {exc}") from exc
            self.esperar_carregar()
            if self._logado(self.cfg.timeout_s):
                log.info("Login realizado")
                return
            raise ErroPortal("Login automatico nao chegou na tela inicial do portal.")
        if self.cfg.headless:
            raise ErroPortal("Nao ha sessao aberta e o navegador esta sem janela: rode uma vez "
                             "com a janela (headless: false) e faca o login.")
        log.info("Aguardando o login manual no navegador (ate %d min)...", self.cfg.espera_login_min)
        if not self._logado(self.cfg.espera_login_min * 60):
            raise ErroPortal("O login nao foi feito dentro do prazo.")
        log.info("Login realizado pelo usuario")

    # -------------------------------------------------------------- navegacao
    def ir_para_lista(self) -> None:
        for passo in self.cfg.caminho:
            log.info("Acessando %s", passo)
            self.clicar(passo, passo)
        log.info('Localizando "Lista de arquivos" do SAGA2 - VH47')
        prazo = time.monotonic() + self.cfg.timeout_s
        while True:
            for page, frame in self._frames():
                try:
                    r = frame.evaluate(_JS_LINK_DO_RELATORIO, [self.cfg.relatorio, self.cfg.link_lista])
                except Exception:  # noqa: BLE001
                    continue
                if r.get("ok"):
                    abas_antes = set(id(p) for p in self.ctx.pages)
                    frame.locator("[data-rpa-alvo='1']").first.click()
                    self._seguir_clique(page, abas_antes)
                    self._esperar_tabela()
                    log.info("Lista de arquivos carregada")
                    return
            if time.monotonic() >= prazo:
                raise ErroPortal('Nao achei o link "Lista de arquivos" do relatorio SAGA2 - VH47 '
                                 f"(regex relatorio: {self.cfg.relatorio}).")
            self._pausa(0.5)

    def _esperar_tabela(self) -> None:
        prazo = time.monotonic() + self.cfg.timeout_s
        while time.monotonic() < prazo:
            if self._ler_tabelas():
                return
            self._pausa(0.5)
        raise ErroPortal("A pagina da Lista de arquivos abriu, mas nao achei a tabela "
                         "(colunas Ano/Mes/DN/Nome do arquivo).")

    # ------------------------------------------------------------------ lista
    def _ler_tabelas(self) -> list[tuple[Any, dict[str, Any], list[ItemLista]]]:
        achadas = []
        for page, frame in self._frames():
            try:
                tabelas = frame.evaluate(_JS_TABELAS)
            except Exception:  # noqa: BLE001
                continue
            for t in tabelas:
                itens = itens_da_tabela(t, self.cfg.colunas)
                if itens:
                    achadas.append((frame, t, itens))
            if achadas:
                self.page = page
                break
        return achadas

    def listar(self) -> list[ItemLista]:
        itens: list[ItemLista] = []
        for _frame, _t, its in self._ler_tabelas():
            itens.extend(its)
        vistos, unicos = set(), []
        for it in itens:
            if it.id not in vistos:
                vistos.add(it.id)
                unicos.append(it)
        if self._tem_paginacao():
            log.warning("A lista parece ter varias paginas: so a pagina aberta foi lida.")
        return unicos

    def _tem_paginacao(self) -> bool:
        for _page, frame in self._frames():
            try:
                if frame.get_by_role("link", name=re.compile(r"^\s*(pr[oó]xim[ao]|>|>>|»)\s*$", re.I)).count():
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    # ---------------------------------------------------------------- download
    def _link_da_linha(self, item: ItemLista):
        for frame, t, itens in self._ler_tabelas():
            for it in itens:
                if it.id == item.id:
                    linha = frame.locator(f"table[data-rpa-tabela='{t['tabela']}'] tr[data-rpa-linha='{it.indice}']").first
                    nome = linha.get_by_text(item.nome, exact=False)
                    for loc in (linha.locator("a", has_text=item.nome), linha.locator("a[href*='.pdf' i]"),
                                linha.locator("a"), linha.locator("button, input[type=button], input[type=submit], input[type=image]"), nome):
                        if loc.count():
                            return loc.first
        raise ErroPortal(f"Nao achei mais a linha de {item.rotulo} na lista (a pagina mudou?).")

    def baixar(self, item: ItemLista, destino: Path) -> Path:
        """Baixa o PDF do item para ``destino``. So devolve com o PDF inteiro no disco."""
        link = self._link_da_linha(item)
        abas_antes = set(id(p) for p in self.ctx.pages)
        n_downloads = len(self._downloads)
        link.click()
        prazo = time.monotonic() + self.cfg.timeout_download_s
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".parcial")
        while time.monotonic() < prazo:
            if len(self._downloads) > n_downloads:
                download = self._downloads[n_downloads]
                # save_as espera o fim do download (o .crdownload e do navegador).
                download.save_as(str(parcial))
                falha = download.failure()
                if falha:
                    parcial.unlink(missing_ok=True)
                    raise ErroPortal(f"download falhou: {falha}")
                self._fechar_abas_novas(abas_antes)
                break
            novas = [p for p in self.ctx.pages if id(p) not in abas_antes and not p.is_closed()]
            pdf = next((p for p in novas if self._parece_pdf(p)), None)
            if pdf is not None:
                # PDF aberto no visualizador em vez de baixado: busca com a mesma sessao.
                resp = self.ctx.request.get(pdf.url, timeout=self.cfg.timeout_download_s * 1000)
                if not resp.ok:
                    raise ErroPortal(f"download falhou: HTTP {resp.status} em {pdf.url}")
                parcial.write_bytes(resp.body())
                self._fechar_abas_novas(abas_antes)
                break
            self._pausa(0.3)
        else:
            self._fechar_abas_novas(abas_antes)
            raise ErroPortal(f"o download nao comecou em {self.cfg.timeout_download_s}s")

        try:
            validar_pdf(parcial)
        except ErroExtracao as exc:
            quarentena = destino.with_name(destino.stem + ".invalido")
            os.replace(parcial, quarentena)
            raise ErroPortal(f"arquivo baixado invalido ({exc}); guardado em {quarentena.name}") from exc
        os.replace(parcial, destino)
        return destino

    def _parece_pdf(self, page) -> bool:
        url = (page.url or "").lower()
        if url.endswith(".pdf") or ".pdf?" in url:
            return True
        if not url or url == "about:blank":
            return False
        try:  # visualizador de PDF do Edge/Chrome em URL sem ".pdf" (ex.: download.aspx?id=)
            return page.evaluate("document.contentType") == "application/pdf"
        except Exception:  # noqa: BLE001
            return False

    def _fechar_abas_novas(self, abas_antes: set[int]) -> None:
        for p in list(self.ctx.pages):
            if id(p) not in abas_antes and not p.is_closed() and p is not self.page:
                try:
                    p.close()
                except Exception:  # noqa: BLE001
                    pass


def carregar_login_automatico(raiz_projeto: Path) -> Callable[[Any], None] | None:
    """Reaproveita o login do rpa_portal_vw.py (mesmo robo, mesmos seletores).

    So e usado se RPA_PORTALVW_USUARIO e RPA_PORTALVW_SENHA estiverem no .env;
    sem eles o login e manual. Nao duplica a logica: importa o script existente.
    """
    usuario = os.environ.get("RPA_PORTALVW_USUARIO", "").strip()
    senha = os.environ.get("RPA_PORTALVW_SENHA", "")
    if not usuario or not senha:
        return None
    candidatos = [raiz_projeto / "scripts" / "rpa_portal_vw.py", Path(r"C:\datalake\rpa_portal_vw.py")]
    script = next((c for c in candidatos if c.is_file()), None)
    if script is None:
        log.warning("rpa_portal_vw.py nao encontrado: login fica manual.")
        return None
    spec = importlib.util.spec_from_file_location("rpa_portal_vw", script)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # type: ignore[union-attr]
    cfg = modulo.ler_config(modulo.achar_config(None))

    def login(page) -> None:
        modulo.fazer_login(page, cfg, usuario, senha, int(cfg["timeout_s"]) * 1000)

    return login
