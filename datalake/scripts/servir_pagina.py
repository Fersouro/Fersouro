# -*- coding: utf-8 -*-
"""
Servidor local simples para a pagina de Estoque Minimo.

Publica a pasta export do lake numa porta HTTP da rede interna. Assim o
pessoal acessa por um link (http://IP-DO-SERVIDOR:8080) em vez de abrir o
arquivo pelo compartilhamento.

    python servir_pagina.py                     # porta 8080, pasta C:\datalake\export
    python servir_pagina.py 8090 C:\datalake\export

Deixe rodando (ou coloque numa Tarefa Agendada disparada na inicializacao).
So serve arquivos -- nao executa nada, nao escreve nada.
"""
import os
import sys
import socket
import functools
import http.server
import socketserver

PORTA = 8080
PASTA = r"C:\datalake\export"


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # raiz abre direto a pagina de estoque
        if self.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/estoque_minimo.html")
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


def main():
    porta = PORTA
    pasta = PASTA
    for a in sys.argv[1:]:
        if a.isdigit():
            porta = int(a)
        elif os.path.isdir(a):
            pasta = a
    if not os.path.isdir(pasta):
        print("Pasta nao existe:", pasta)
        return 1
    handler = functools.partial(Handler, directory=pasta)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", porta), handler) as httpd:
        print("Servindo", pasta)
        print("Acesse na rede:  http://%s:%d/" % (ip_local(), porta))
        print("(Ctrl+C para parar)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nParado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
