# -*- coding: utf-8 -*-
"""
Servidor local da pagina de Estoque Minimo e dos relatorios.

Publica a pasta export do lake numa porta HTTPS da rede interna. Assim o
pessoal acessa por um link (https://IP-DO-SERVIDOR:8443) em vez de abrir o
arquivo pelo compartilhamento.

    python servir_pagina.py                          # HTTPS na 8443
    python servir_pagina.py --host 192.168.78.6      # so nessa placa de rede
    python servir_pagina.py --porta 8443 --pasta C:\\datalake\\export
    python servir_pagina.py --http 8080              # como era antes, sem TLS
    python servir_pagina.py --criar-usuario fernando # cadastra quem pode entrar

O acesso pede usuario e senha: a pasta export tem margem e faturamento, e sem
login qualquer maquina da rede baixa tudo. As senhas ficam com hash pbkdf2 em
<pasta-pai-do-export>\\usuarios.json; as sessoes vivem na memoria (reiniciou o
servico, todo mundo entra de novo). Para o comportamento antigo, --sem-login.

A forma antiga ("servir_pagina.py 8080 C:\\datalake\\export", que a Tarefa
Agendada registrada antes desta versao usa) continua servindo HTTP na porta
pedida -- trocar o protocolo sem ninguem pedir quebraria o link salvo. Rode o
instalar_servidor.ps1 para passar a tarefa para o HTTPS.

O certificado e gerado sozinho na primeira execucao (autoassinado, 10 anos,
em <pasta-pai-do-export>\\cert). Ele cobre o nome da maquina e todos os IPs
dela, entao vale para qualquer endereco pelo qual o servidor for chamado.
Como e autoassinado, o navegador avisa na primeira visita -- e uso interno;
para tirar o aviso, instale o certificado como confiavel nas maquinas (ou
distribua por GPO).

A porta antiga (8080) continua respondendo: quem tiver o link velho salvo e
redirecionado para o HTTPS, em vez de tomar erro.

So serve arquivos -- nao executa nada, nao escreve nada (fora o certificado).
"""
import os
import sys
import ssl
import html
import hmac
import json
import time
import socket
import secrets
import getpass
import hashlib
import datetime
import functools
import threading
import http.server
import socketserver
import urllib.parse

PORTA_HTTPS = 8443
PORTA_HTTP = 8080            # so redireciona para o HTTPS
PASTA = r"C:\datalake\export"
PAGINA = "/estoque_minimo.html"


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def ips_da_maquina():
    """Todos os IPv4 do servidor -- entram no certificado."""
    ips = {"127.0.0.1", ip_local()}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass
    return sorted(ips)


# ------------------------------------------------------------- certificado


def gerar_certificado(cert, chave, extras=()):
    """Certificado autoassinado cobrindo o nome da maquina e os IPs dela.

    -> (ok, motivo). O import vem dentro de try amplo de proposito: instalacao
    quebrada do 'cryptography' nao levanta ImportError, ela estoura no binario
    nativo -- e derrubar o servidor com stack trace nao ajuda ninguem.
    """
    try:
        import ipaddress
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except BaseException as exc:      # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)

    nome = socket.gethostname()
    alternativos = [x509.DNSName(nome), x509.DNSName("localhost")]
    # O endereco pelo qual o servidor e chamado entra no certificado: sem isso
    # o navegador reclama do nome mesmo depois de o certificado ser aceito.
    for extra in extras:
        try:
            alternativos.append(x509.IPAddress(ipaddress.ip_address(extra)))
        except ValueError:
            alternativos.append(x509.DNSName(extra))
    for ip in ips_da_maquina():
        try:
            alternativos.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass

    try:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        sujeito = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, nome),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Datalake"),
        ])
        agora = datetime.datetime.now(datetime.timezone.utc)
        certificado = (
            x509.CertificateBuilder()
            .subject_name(sujeito)
            .issuer_name(sujeito)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - datetime.timedelta(days=1))
            .not_valid_after(agora + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )

        os.makedirs(os.path.dirname(cert), exist_ok=True)
        with open(chave, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        with open(cert, "wb") as f:
            f.write(certificado.public_bytes(serialization.Encoding.PEM))
    except BaseException as exc:      # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)

    try:
        os.chmod(chave, 0o600)
    except OSError:
        pass
    return True, None


def contexto_tls(cert, chave, extras=()):
    """Prepara o TLS, gerando o certificado se ainda nao existir. -> ctx|None."""
    if not (os.path.isfile(cert) and os.path.isfile(chave)):
        print("Gerando certificado autoassinado em", cert)
        ok, motivo = gerar_certificado(cert, chave, extras)
        if not ok:
            print("Nao consegui gerar o certificado --", motivo)
            print("")
            print("Servir em HTTPS depende do pacote 'cryptography':")
            print("    pip install cryptography")
            print("Ou informe um certificado proprio: --cert arquivo.pem --key arquivo.key")
            print("Ou rode sem TLS (como era antes):  --http 8080")
            return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert, keyfile=chave)
    except (ssl.SSLError, OSError) as exc:
        print("Certificado invalido em %s -- %s" % (cert, exc))
        print("Apague a pasta do certificado para gera-lo de novo.")
        return None
    return ctx


# ------------------------------------------------------------------- login
#
# A pagina e os relatorios trazem numero de faturamento e margem. Servir isso
# aberto na rede interna significa que qualquer maquina do escritorio baixa a
# planilha inteira. Entao o servidor pede usuario e senha, e as sessoes moram
# na memoria -- reiniciou o servico, todo mundo entra de novo.

SESSAO_HORAS = 12
MAX_TENTATIVAS = 5           # por IP
JANELA_BLOQUEIO = 300        # segundos
ITERACOES = 240_000
COOKIE = "datalake_sessao"
TITULO = "Relatorios Tterrasul"


def _hash_senha(senha, sal, iteracoes=ITERACOES):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes).hex()


def carregar_usuarios(caminho):
    """Le o arquivo de usuarios. -> dict (vazio se nao existir)."""
    if not os.path.isfile(caminho):
        return {}
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError) as exc:
        print("Arquivo de usuarios ilegivel (%s): %s" % (caminho, exc))
        return {}
    return dados.get("usuarios") or {}


def gravar_usuario(caminho, nome, senha):
    """Cria ou troca a senha de um usuario. A senha nunca e gravada em claro."""
    usuarios = carregar_usuarios(caminho)
    sal = secrets.token_bytes(16)
    usuarios[nome.strip().lower()] = {
        "algoritmo": "pbkdf2_sha256",
        "iteracoes": ITERACOES,
        "sal": sal.hex(),
        "hash": _hash_senha(senha, sal),
        "atualizado_em": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"usuarios": usuarios}, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(caminho, 0o600)
    except OSError:
        pass
    return sorted(usuarios)


def senha_confere(registro, senha):
    """Compara em tempo constante -- comparar com '==' vaza o tamanho do acerto."""
    try:
        sal = bytes.fromhex(registro["sal"])
        esperado = registro["hash"]
        iteracoes = int(registro.get("iteracoes") or ITERACOES)
    except (KeyError, ValueError):
        return False
    return hmac.compare_digest(_hash_senha(senha, sal, iteracoes), esperado)


class Sessoes:
    """Sessoes e tentativas de login, protegidas por lock (o servidor e threaded)."""

    def __init__(self, horas=SESSAO_HORAS):
        self._itens = {}
        self._falhas = {}
        self._lock = threading.Lock()
        self._duracao = horas * 3600

    def criar(self, usuario):
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._itens[token] = (usuario, time.time() + self._duracao)
        return token

    def usuario(self, token):
        if not token:
            return None
        with self._lock:
            dados = self._itens.get(token)
            if not dados:
                return None
            usuario, expira = dados
            if time.time() > expira:
                del self._itens[token]
                return None
            return usuario

    def encerrar(self, token):
        with self._lock:
            self._itens.pop(token, None)

    def bloqueado(self, ip):
        with self._lock:
            recentes = [t for t in self._falhas.get(ip, []) if time.time() - t < JANELA_BLOQUEIO]
            self._falhas[ip] = recentes
            return len(recentes) >= MAX_TENTATIVAS

    def registrar_falha(self, ip):
        with self._lock:
            self._falhas.setdefault(ip, []).append(time.time())

    def limpar_falhas(self, ip):
        with self._lock:
            self._falhas.pop(ip, None)


# ------------------------------------------------------------------ paginas

_ESTILO = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; font:15px/1.5 "Segoe UI",system-ui,sans-serif;
       background:#0f172a; color:#e2e8f0; }
a { color:#60a5fa; text-decoration:none; } a:hover { text-decoration:underline; }
.centro { min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }
.cartao { width:100%; max-width:380px; background:#131c31; border:1px solid #1e293b;
          border-radius:12px; padding:32px; }
h1 { margin:0 0 6px; font-size:22px; } h2 { font-size:15px; margin:28px 0 10px; color:#94a3b8;
     text-transform:uppercase; letter-spacing:.04em; }
.sub { margin:0 0 24px; color:#94a3b8; font-size:14px; }
label { display:block; margin:14px 0 6px; font-size:13px; color:#cbd5e1; }
input { width:100%; padding:10px 12px; border-radius:8px; border:1px solid #24314d;
        background:#0b1324; color:#e2e8f0; font-size:15px; }
input:focus { outline:2px solid #2563eb; outline-offset:1px; }
button { width:100%; margin-top:22px; padding:11px; border:0; border-radius:8px;
         background:#2563eb; color:#fff; font-size:15px; font-weight:600; cursor:pointer; }
button:hover { background:#1d4ed8; }
.rodape { margin-top:26px; text-align:center; color:#64748b; font-size:12px; line-height:1.7; }
.erro { margin-top:16px; padding:10px 12px; border-radius:8px; background:#3f1d1d;
        border:1px solid #7f1d1d; color:#fecaca; font-size:14px; }
.painel { max-width:900px; margin:0 auto; padding:32px 24px 64px; }
.topo { display:flex; align-items:baseline; justify-content:space-between; gap:16px;
        border-bottom:1px solid #1e293b; padding-bottom:16px; margin-bottom:8px; }
.destaque { display:block; margin:18px 0; padding:18px 20px; border-radius:10px;
            background:#132a4a; border:1px solid #1e3a5f; color:#e2e8f0; }
.destaque strong { display:block; font-size:17px; color:#fff; }
.destaque span { color:#94a3b8; font-size:13px; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:9px 8px; border-bottom:1px solid #1e293b; font-size:14px; }
th { color:#94a3b8; font-weight:600; font-size:12px; text-transform:uppercase; }
td.n { text-align:right; color:#94a3b8; white-space:nowrap; }
.vazio { color:#64748b; font-size:14px; padding:10px 0; }
"""


def _moldura(titulo, corpo, centro=True):
    return ("<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body>%s</body></html>"
            % (html.escape(titulo), _ESTILO,
               ("<div class='centro'>%s</div>" % corpo) if centro else corpo))


def pagina_login(proximo="/", erro=None):
    aviso = "<div class='erro'>%s</div>" % html.escape(erro) if erro else ""
    corpo = """
      <form class="cartao" method="post" action="/entrar">
        <h1>%s</h1>
        <p class="sub">Entre com seu usuário da empresa.</p>
        <input type="hidden" name="proximo" value="%s">
        <label for="u">Usuário</label>
        <input id="u" name="usuario" autocomplete="username" autofocus required>
        <label for="s">Senha</label>
        <input id="s" name="senha" type="password" autocomplete="current-password" required>
        <button type="submit">Entrar</button>
        %s
        <p class="rodape">Acesso restrito à rede interna.<br>Não tem usuário? Fale com o Fernando.</p>
      </form>""" % (html.escape(TITULO), html.escape(proximo), aviso)
    return _moldura(TITULO, corpo)


def _tabela(arquivos, prefixo):
    if not arquivos:
        return "<p class='vazio'>Nada gerado ainda — rode uma carga.</p>"
    linhas = []
    for nome, tamanho, quando in arquivos:
        linhas.append(
            "<tr><td><a href='%s%s'>%s</a></td><td class='n'>%s</td><td class='n'>%s</td></tr>"
            % (prefixo, urllib.parse.quote(nome), html.escape(nome),
               "%.1f KB" % (tamanho / 1024.0), quando)
        )
    return ("<table><tr><th>Arquivo</th><th class='n'>Tamanho</th>"
            "<th class='n'>Atualizado</th></tr>%s</table>" % "".join(linhas))


def pagina_painel(usuario, pasta):
    def listar(sub):
        caminho = os.path.join(pasta, sub) if sub else pasta
        if not os.path.isdir(caminho):
            return []
        itens = []
        for nome in sorted(os.listdir(caminho)):
            inteiro = os.path.join(caminho, nome)
            if os.path.isfile(inteiro) and nome.lower().endswith((".xlsx", ".csv")):
                st = os.stat(inteiro)
                quando = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")
                itens.append((nome, st.st_size, quando))
        return itens

    estoque = ""
    if os.path.isfile(os.path.join(pasta, PAGINA.lstrip("/"))):
        st = os.stat(os.path.join(pasta, PAGINA.lstrip("/")))
        quando = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")
        estoque = ("<a class='destaque' href='%s'><strong>Estoque Mínimo de Peças</strong>"
                   "<span>Disponível × mínimo, com histórico por data — atualizado em %s</span></a>"
                   % (PAGINA, quando))

    corpo = """
      <div class="painel">
        <div class="topo">
          <div><h1>%s</h1><p class="sub">Olá, %s.</p></div>
          <a href="/sair">Sair</a>
        </div>
        %s
        <h2>Relatórios</h2>
        %s
        <h2>Modelos exportados</h2>
        %s
      </div>""" % (html.escape(TITULO), html.escape(usuario), estoque,
                   _tabela(listar("relatorios"), "/relatorios/"),
                   _tabela(listar(""), "/"))
    return _moldura(TITULO, corpo, centro=False)


# ---------------------------------------------------------------- handlers


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serve a pasta export -- so para quem entrou com usuario e senha."""

    usuarios = {}
    sessoes = None
    exige_login = True

    # ---- sessao -----------------------------------------------------------
    def _token(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            nome, _, valor = parte.strip().partition("=")
            if nome == COOKIE:
                return valor
        return None

    def _usuario(self):
        if not self.exige_login:
            return "convidado"
        return self.sessoes.usuario(self._token())

    # ---- respostas --------------------------------------------------------
    def _html(self, corpo, codigo=200):
        dados = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _ir_para(self, destino, cookie=None):
        self.send_response(302)
        self.send_header("Location", destino)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _caminho(self):
        return urllib.parse.urlsplit(self.path).path

    def _destino_seguro(self, bruto):
        """So aceita caminho interno: '//outro.site' num redirect vira phishing."""
        if not bruto or not bruto.startswith("/") or bruto.startswith("//"):
            return "/"
        return bruto

    # ---- rotas ------------------------------------------------------------
    def do_GET(self):
        caminho = self._caminho()
        if self.exige_login:
            if caminho == "/entrar":
                consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                proximo = self._destino_seguro((consulta.get("proximo") or ["/"])[0])
                if self._usuario():
                    return self._ir_para(proximo)
                return self._html(pagina_login(proximo))
            if caminho == "/sair":
                self.sessoes.encerrar(self._token())
                return self._ir_para("/entrar", COOKIE + "=; Max-Age=0; Path=/; HttpOnly")

        usuario = self._usuario()
        if usuario is None:
            return self._ir_para("/entrar?proximo=" + urllib.parse.quote(self.path))
        if caminho in ("/", "/index.html"):
            return self._html(pagina_painel(usuario, self.directory))
        super().do_GET()

    def do_HEAD(self):
        # Sem isto, um HEAD baixaria os cabecalhos de qualquer arquivo sem login.
        if self._usuario() is None:
            return self._ir_para("/entrar")
        super().do_HEAD()

    def do_POST(self):
        if not self.exige_login or self._caminho() != "/entrar":
            return self.send_error(405)

        ip = self.client_address[0]
        if self.sessoes.bloqueado(ip):
            return self._html(
                pagina_login("/", "Muitas tentativas. Espere alguns minutos."), 429
            )

        tamanho = min(int(self.headers.get("Content-Length") or 0), 4096)
        campos = urllib.parse.parse_qs(self.rfile.read(tamanho).decode("utf-8", "replace"))
        nome = (campos.get("usuario") or [""])[0].strip().lower()
        senha = (campos.get("senha") or [""])[0]
        proximo = self._destino_seguro((campos.get("proximo") or ["/"])[0])

        registro = self.usuarios.get(nome)
        if not registro or not senha_confere(registro, senha):
            self.sessoes.registrar_falha(ip)
            time.sleep(1)          # tira a graca de tentar senha em massa
            return self._html(pagina_login(proximo, "Usuário ou senha inválidos."), 401)

        self.sessoes.limpar_falhas(ip)
        seguro = "; Secure" if getattr(self.server, "tls", False) else ""
        self._ir_para(proximo, "%s=%s; Path=/; HttpOnly; SameSite=Lax%s"
                               % (COOKIE, self.sessoes.criar(nome), seguro))

    def end_headers(self):
        # A pagina e regerada a cada carga. Sem isso o navegador mostra a
        # versao velha do cache e parece que "nada mudou".
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def log_message(self, *a):
        pass  # silencioso


class Redirecionador(http.server.BaseHTTPRequestHandler):
    """Responde na porta antiga mandando para o HTTPS -- link velho continua valendo."""

    porta_destino = PORTA_HTTPS

    def do_GET(self):
        anfitriao = (self.headers.get("Host") or ip_local()).split(":")[0]
        destino = "https://%s:%d%s" % (anfitriao, self.porta_destino, self.path)
        self.send_response(301)
        self.send_header("Location", destino)
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, *a):
        pass


def subir_redirecionador(host, porta_antiga, porta_destino):
    """Sobe o redirecionador numa thread. Porta ocupada e aviso, nao erro."""
    handler = type("R", (Redirecionador,), {"porta_destino": porta_destino})
    try:
        servidor = socketserver.TCPServer((host, porta_antiga), handler)
    except OSError as exc:
        print("(porta %d nao redireciona: %s)" % (porta_antiga, exc))
        return None
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


# -------------------------------------------------------------------- main


def parse_args(argv):
    """Aceita as flags novas e a forma antiga (porta e pasta soltas)."""
    opcoes = {
        "host": "0.0.0.0", "porta": None, "pasta": None, "tls": True,
        "cert": None, "chave": None, "redirecionar_de": PORTA_HTTP,
        "usuarios": None, "sem_login": False, "criar_usuario": None,
    }
    # A Tarefa Agendada antiga chama "servir_pagina.py 8080 C:\datalake\export".
    # Se ela continuar valendo depois de uma atualizacao de codigo, tem que
    # seguir servindo HTTP na 8080 como antes -- trocar para HTTPS sem trocar a
    # tarefa deixaria o link antigo quebrado sem ninguem pedir. Quem quer o
    # HTTPS roda o instalar_servidor.ps1, que registra a tarefa com as flags.
    legado = False
    explicito = False
    i = 0
    while i < len(argv):
        a = argv[i]
        proximo = argv[i + 1] if i + 1 < len(argv) else None
        if a in ("--host", "-h"):
            opcoes["host"] = proximo; i += 2
        elif a in ("--porta", "-p"):
            opcoes["porta"] = int(proximo); explicito = True; i += 2
        elif a == "--pasta":
            opcoes["pasta"] = proximo; i += 2
        elif a == "--cert":
            opcoes["cert"] = proximo; i += 2
        elif a in ("--key", "--chave"):
            opcoes["chave"] = proximo; i += 2
        elif a in ("--https", "--tls"):
            opcoes["tls"] = True; explicito = True; i += 1
        elif a == "--http":
            opcoes["tls"] = False; explicito = True
            if proximo and proximo.isdigit():
                opcoes["porta"] = int(proximo); i += 1
            i += 1
        elif a == "--usuarios":
            opcoes["usuarios"] = proximo; i += 2
        elif a == "--criar-usuario":
            opcoes["criar_usuario"] = proximo; i += 2
        elif a == "--sem-login":
            opcoes["sem_login"] = True; i += 1
        elif a == "--sem-redirecionar":
            opcoes["redirecionar_de"] = None; i += 1
        elif a == "--redirecionar-de":
            opcoes["redirecionar_de"] = int(proximo); i += 2
        elif a.isdigit():                      # forma antiga: porta solta
            opcoes["porta"] = int(a); legado = True; i += 1
        elif os.path.isdir(a):                 # forma antiga: pasta solta
            opcoes["pasta"] = a; legado = True; i += 1
        else:
            print("Argumento nao reconhecido:", a)
            return None

    if legado and not explicito:
        opcoes["tls"] = False
        opcoes["redirecionar_de"] = None
    return opcoes


def criar_usuario(caminho, nome):
    """Pede a senha duas vezes e grava. A senha nao passa por argumento de
    linha de comando de proposito: argumento aparece na lista de processos."""
    senha = getpass.getpass("Senha para '%s': " % nome)
    if len(senha) < 6:
        print("Senha muito curta (minimo 6 caracteres).")
        return 1
    if senha != getpass.getpass("Repita a senha: "):
        print("As senhas nao conferem.")
        return 1
    usuarios = gravar_usuario(caminho, nome, senha)
    print("Usuario '%s' gravado em %s" % (nome.strip().lower(), caminho))
    print("Usuarios cadastrados:", ", ".join(usuarios))
    return 0


def main():
    opcoes = parse_args(sys.argv[1:])
    if opcoes is None:
        return 2

    pasta = opcoes["pasta"] or PASTA
    porta = opcoes["porta"] or (PORTA_HTTPS if opcoes["tls"] else PORTA_HTTP)
    raiz = os.path.dirname(os.path.abspath(pasta))            # C:\datalake
    arquivo_usuarios = opcoes["usuarios"] or os.path.join(raiz, "usuarios.json")

    if opcoes["criar_usuario"]:
        return criar_usuario(arquivo_usuarios, opcoes["criar_usuario"])

    if not os.path.isdir(pasta):
        print("Pasta nao existe:", pasta)
        return 1

    usuarios = {} if opcoes["sem_login"] else carregar_usuarios(arquivo_usuarios)
    if not opcoes["sem_login"] and not usuarios:
        print("Nenhum usuario cadastrado em", arquivo_usuarios)
        print("")
        print("Crie o primeiro antes de subir o servidor:")
        print("    python servir_pagina.py --criar-usuario fernando")
        print("Ou, para servir sem senha (nao recomendado -- a pasta tem margem")
        print("e faturamento):  --sem-login")
        return 1

    ctx = None
    if opcoes["tls"]:
        cert = opcoes["cert"] or os.path.join(raiz, "cert", "servidor.pem")
        chave = opcoes["chave"] or os.path.join(raiz, "cert", "servidor.key")
        extras = [] if opcoes["host"] in ("0.0.0.0", "::", "") else [opcoes["host"]]
        ctx = contexto_tls(cert, chave, extras)
        if ctx is None:
            return 1

    esquema = "https" if ctx else "http"
    # Uma classe por execucao: e assim que a lista de usuarios e as sessoes
    # chegam ao handler, que o http.server instancia a cada requisicao.
    configurado = type("HandlerConfigurado", (Handler,), {
        "usuarios": usuarios,
        "sessoes": Sessoes(),
        "exige_login": not opcoes["sem_login"],
    })
    handler = functools.partial(configurado, directory=pasta)
    socketserver.TCPServer.allow_reuse_address = True
    try:
        # Threaded: o login dorme 1s a cada senha errada, e um servidor de uma
        # conexao so deixaria todo mundo esperando nessa pausa.
        httpd = http.server.ThreadingHTTPServer((opcoes["host"], porta), handler)
    except OSError as exc:
        print("Nao consegui abrir %s:%d -- %s" % (opcoes["host"], porta, exc))
        print("(outra coisa ja usa essa porta? veja com: netstat -ano | findstr :%d)" % porta)
        return 1
    httpd.tls = bool(ctx)
    if ctx:
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    antiga = None
    if ctx and opcoes["redirecionar_de"] and opcoes["redirecionar_de"] != porta:
        antiga = subir_redirecionador(opcoes["host"], opcoes["redirecionar_de"], porta)

    with httpd:
        print("Servindo", pasta)
        print("Acesse na rede:  %s://%s:%d/" % (esquema, ip_local(), porta))
        if antiga:
            print("Porta %d redireciona para o %s." % (opcoes["redirecionar_de"], esquema.upper()))
        if ctx:
            print("Certificado autoassinado: o navegador avisa na primeira visita.")
        if opcoes["sem_login"]:
            print("SEM LOGIN: qualquer maquina da rede baixa as planilhas.")
        else:
            print("Login exigido. Usuarios em %s (%d cadastrado(s))."
                  % (arquivo_usuarios, len(usuarios)))
        print("(Ctrl+C para parar)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nParado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
