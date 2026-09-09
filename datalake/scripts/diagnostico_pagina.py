# -*- coding: utf-8 -*-
"""
Diz por que o login da pagina nao passa -- em um comando so.

    python C:\\datalake\\diagnostico_pagina.py

Responde as tres perguntas que o navegador nao responde:

  1. QUEM esta atendendo em cada porta (este servidor, outro portal, ninguem);
  2. em que porta a Tarefa Agendada sobe o servidor do datalake;
  3. QUEM esta cadastrado no usuarios.json que esse servidor le.

Nao mostra senha nem hash, e nao muda nada -- so olha e conta.
"""
from __future__ import annotations

import io
import os
import re
import ssl
import sys
import json
import socket
import datetime
import subprocess
import urllib.request

PORTAS = (8443, 8444, 8080)
LAKE = r"C:\datalake" if os.name == "nt" else os.getcwd()
TAREFA = "DatalakeEstoquePagina"


def titulo(texto):
    print("\n" + texto)
    print("-" * len(texto))


def _sem_verificar_certificado():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def quem_responde(porta, host="127.0.0.1", timeout=4):
    """-> (situacao, detalhe). Nao levanta excecao: aqui tudo e informacao."""
    with socket.socket() as s:
        s.settimeout(timeout)
        if s.connect_ex((host, porta)) != 0:
            return "livre", "ninguem escutando"

    for esquema in ("https", "http"):
        url = "%s://%s:%d/versao" % (esquema, host, porta)
        try:
            with urllib.request.urlopen(
                    url, timeout=timeout, context=_sem_verificar_certificado()) as r:
                corpo = r.read(2048).decode("utf-8", "replace")
            try:
                dados = json.loads(corpo)
            except ValueError:
                return "outro", "%s responde, mas /versao nao e JSON" % esquema.upper()
            if dados.get("servidor") == "datalake-servir-pagina":
                return "datalake", "%s, versao %s, login=%s, gerador=%s" % (
                    esquema.upper(), dados.get("versao"), dados.get("login"),
                    dados.get("gerador"))
            return "outro", "%s, mas se identifica como %r" % (esquema.upper(), dados)
        except Exception as exc:            # noqa: BLE001
            ultimo = "%s: %s" % (esquema.upper(), exc)
    return "outro", "porta ocupada por um servidor que nao tem /versao (%s)" % ultimo


def processo_da_porta(porta):
    """No Windows, o programa que segura a porta -- com a linha de comando."""
    if os.name != "nt":
        return None
    try:
        saida = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=20)
        texto = saida.stdout.decode("latin-1", "replace")
    except Exception:                        # noqa: BLE001
        return None
    pids = set()
    for linha in texto.splitlines():
        if ":%d " % porta in linha and "LISTENING" in linha.upper():
            partes = linha.split()
            if partes and partes[-1].isdigit():
                pids.add(partes[-1])
    achados = []
    for pid in sorted(pids):
        comando = None
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Process -Filter \"ProcessId=%s\")."
                 "CommandLine" % pid],
                capture_output=True, timeout=30)
            comando = r.stdout.decode("latin-1", "replace").strip()
        except Exception:                    # noqa: BLE001
            pass
        achados.append((pid, comando or "(linha de comando indisponivel)"))
    return achados


def tarefa_agendada():
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TAREFA, "/V", "/FO", "LIST"],
                           capture_output=True, timeout=30)
        texto = r.stdout.decode("latin-1", "replace")
    except Exception:                        # noqa: BLE001
        return None
    if r.returncode != 0:
        return "(tarefa '%s' nao existe)" % TAREFA
    for linha in texto.splitlines():
        if re.search(r"(Tarefa a ser executada|Task To Run)", linha, re.I):
            return linha.split(":", 1)[1].strip()
    return "(tarefa existe, mas nao achei a linha de comando)"


def usuarios(caminho):
    if not os.path.isfile(caminho):
        return None
    try:
        with io.open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception as exc:                 # noqa: BLE001
        return "ILEGIVEL: %s" % exc
    itens = (dados or {}).get("usuarios") or {}
    return [(nome, reg.get("atualizado_em", "?")) for nome, reg in sorted(itens.items())]


def main():
    lake = sys.argv[1] if len(sys.argv) > 1 else LAKE
    print("=== diagnostico da pagina de relatorios ===")
    print("lake:", lake, "|", datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))

    titulo("1. Quem atende em cada porta")
    situacoes = {}
    for porta in PORTAS:
        situacao, detalhe = quem_responde(porta)
        situacoes[porta] = situacao
        print("  %-5d %-9s %s" % (porta, situacao.upper(), detalhe))
        for pid, comando in (processo_da_porta(porta) or []):
            print("        pid %s: %s" % (pid, comando[:150]))

    titulo("2. Como a Tarefa Agendada sobe o servidor")
    print(" ", tarefa_agendada() or "(so no Windows)")

    titulo("3. Quem esta cadastrado")
    caminho = os.path.join(lake, "usuarios.json")
    print("  arquivo:", caminho)
    lista = usuarios(caminho)
    if lista is None:
        print("  NAO EXISTE -- ninguem consegue entrar neste servidor.")
        print("  Crie o primeiro:  python %s --criar-usuario <nome>"
              % os.path.join(lake, "servir_pagina.py"))
    elif isinstance(lista, str):
        print(" ", lista)
    elif not lista:
        print("  arquivo existe, mas esta vazio.")
    else:
        for nome, quando in lista:
            print("  - %s   (senha gravada em %s)" % (nome, quando))

    titulo("Veredito")
    if situacoes.get(8443) == "datalake":
        print("  A 8443 e o servidor do datalake. Se o login recusa, o problema e")
        print("  usuario ou senha -- confira com:")
        print("    python %s --verificar-senha <usuario>"
              % os.path.join(lake, "servir_pagina.py"))
    elif situacoes.get(8443) == "outro":
        print("  A 8443 NAO e o servidor do datalake: e outro portal, com a")
        print("  propria lista de usuarios. Por isso o usuario criado aqui nao entra la.")
        for porta in (8444, 8080):
            if situacoes.get(porta) == "datalake":
                print("  O servidor do datalake esta na porta %d." % porta)
                print("  Acesse https://IP-DO-SERVIDOR:%d/ -- ou troque as portas." % porta)
                break
        else:
            print("  E o servidor do datalake nao respondeu em nenhuma porta conhecida:")
            print("    schtasks /Run /TN %s" % TAREFA)
    else:
        print("  Ninguem esta atendendo na 8443. Suba o servico:")
        print("    schtasks /Run /TN %s" % TAREFA)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
