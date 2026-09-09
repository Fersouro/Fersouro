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
import socket
import datetime
import functools
import threading
import http.server
import socketserver

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


# ---------------------------------------------------------------- handlers


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # raiz abre direto a pagina de estoque
        if self.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", PAGINA)
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        # A pagina e regerada a cada carga. Sem isso o navegador mostra a
        # versao velha do cache e parece que "nada mudou".
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
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


def main():
    opcoes = parse_args(sys.argv[1:])
    if opcoes is None:
        return 2

    pasta = opcoes["pasta"] or PASTA
    porta = opcoes["porta"] or (PORTA_HTTPS if opcoes["tls"] else PORTA_HTTP)
    if not os.path.isdir(pasta):
        print("Pasta nao existe:", pasta)
        return 1

    ctx = None
    if opcoes["tls"]:
        raiz = os.path.dirname(os.path.abspath(pasta))      # C:\datalake
        cert = opcoes["cert"] or os.path.join(raiz, "cert", "servidor.pem")
        chave = opcoes["chave"] or os.path.join(raiz, "cert", "servidor.key")
        extras = [] if opcoes["host"] in ("0.0.0.0", "::", "") else [opcoes["host"]]
        ctx = contexto_tls(cert, chave, extras)
        if ctx is None:
            return 1

    esquema = "https" if ctx else "http"
    handler = functools.partial(Handler, directory=pasta)
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer((opcoes["host"], porta), handler)
    except OSError as exc:
        print("Nao consegui abrir %s:%d -- %s" % (opcoes["host"], porta, exc))
        print("(outra coisa ja usa essa porta? veja com: netstat -ano | findstr :%d)" % porta)
        return 1
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
        print("(Ctrl+C para parar)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nParado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
