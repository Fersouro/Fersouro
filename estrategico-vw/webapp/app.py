#!/usr/bin/env python3
"""
Servidor do Consolidador Estratégico VW.

Sobe uma página em http://<ip>:<porta> onde o usuário envia o extrato do
DataLake (CSV/XLSX) e baixa a planilha consolidada já cruzada.

Usa apenas a biblioteca padrão do Python (+ openpyxl, via consolidar.py).

    python3 app.py                 # 0.0.0.0:8000
    python3 app.py --porta 8080
    python3 app.py --host 127.0.0.1

Atenção: o servidor não tem autenticação. Use apenas na rede interna.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import sys
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import consolidar

BASE = Path(__file__).resolve().parent
NOME_PLANILHA = "Estrategico_PAC_VII_5.xlsx"


def _achar_planilha_padrao() -> Path:
    """
    Procura a planilha Estratégico na pasta do projeto e ao lado do app.py.

    Assim funciona tanto no repositório (webapp/../planilha.xlsx) quanto quando
    todos os arquivos são copiados soltos para uma única pasta.
    """
    for pasta in (BASE.parent, BASE):
        caminho = pasta / NOME_PLANILHA
        if caminho.exists():
            return caminho
    return BASE.parent / NOME_PLANILHA   # caminho citado na mensagem de erro


PLANILHA_PADRAO = _achar_planilha_padrao()

TAMANHO_MAXIMO = 40 * 1024 * 1024   # 40 MB por requisição
MAX_SESSOES = 30                    # sessões guardadas em memória
VALIDADE_SESSAO = 6 * 3600          # segundos

_sessoes: "OrderedDict[str, dict]" = OrderedDict()
_trava = threading.Lock()


# --------------------------------------------------------------------------- #
# Sessões em memória                                                          #
# --------------------------------------------------------------------------- #
def guardar_sessao(dados: dict) -> str:
    ident = uuid.uuid4().hex
    with _trava:
        agora = time.time()
        vencidas = [k for k, v in _sessoes.items()
                    if agora - v["criada_em"] > VALIDADE_SESSAO]
        for k in vencidas:
            _sessoes.pop(k, None)
        dados["criada_em"] = agora
        _sessoes[ident] = dados
        while len(_sessoes) > MAX_SESSOES:
            _sessoes.popitem(last=False)
    return ident


def obter_sessao(ident: str) -> dict | None:
    with _trava:
        sessao = _sessoes.get(ident)
        if sessao and time.time() - sessao["criada_em"] > VALIDADE_SESSAO:
            _sessoes.pop(ident, None)
            return None
        return sessao


# --------------------------------------------------------------------------- #
# Parser multipart/form-data (stdlib pura; o módulo cgi saiu do Python 3.13)   #
# --------------------------------------------------------------------------- #
def parse_multipart(corpo: bytes, content_type: str) -> dict:
    """Devolve {campo: valor_str} e {campo: {'nome':.., 'dados': bytes}}."""
    marcador = "boundary="
    if marcador not in content_type:
        raise ValueError("Requisição multipart sem boundary.")
    limite = content_type.split(marcador, 1)[1].strip().strip('"')
    sep = b"--" + limite.encode()

    campos: dict = {}
    for parte in corpo.split(sep):
        if parte in (b"", b"--", b"--\r\n", b"\r\n"):
            continue
        parte = parte.lstrip(b"\r\n")
        if parte.startswith(b"--"):
            continue
        if b"\r\n\r\n" not in parte:
            continue
        cabecalho_bruto, conteudo = parte.split(b"\r\n\r\n", 1)
        if conteudo.endswith(b"\r\n"):
            conteudo = conteudo[:-2]

        cabecalho = cabecalho_bruto.decode("utf-8", "replace")
        disposicao = ""
        for linha in cabecalho.split("\r\n"):
            if linha.lower().startswith("content-disposition:"):
                disposicao = linha
                break
        if not disposicao:
            continue

        nome_campo, nome_arquivo = None, None
        for pedaco in disposicao.split(";")[1:]:
            pedaco = pedaco.strip()
            if pedaco.startswith("name="):
                nome_campo = pedaco[5:].strip().strip('"')
            elif pedaco.startswith("filename="):
                nome_arquivo = pedaco[9:].strip().strip('"')
        if not nome_campo:
            continue

        if nome_arquivo is not None:
            campos[nome_campo] = {"nome": nome_arquivo, "dados": conteudo}
        else:
            campos[nome_campo] = conteudo.decode("utf-8", "replace")
    return campos


# --------------------------------------------------------------------------- #
# Processamento                                                               #
# --------------------------------------------------------------------------- #
def _indice(valor, cabecalhos):
    """Converte um índice vindo do formulário; '' e '-1' viram None."""
    if valor in (None, "", "-1", "null"):
        return None
    try:
        i = int(valor)
    except (TypeError, ValueError):
        return None
    return i if 0 <= i < len(cabecalhos) else None


def processar(dados_extrato: bytes, nome_extrato: str, dados_pedido, nome_pedido,
              acrescimo: float, mapa_manual: dict | None = None) -> dict:
    import io

    if dados_pedido:
        itens = consolidar.ler_pedido(io.BytesIO(dados_pedido))
        origem_pedido = nome_pedido
    else:
        if not PLANILHA_PADRAO.exists():
            raise ValueError(
                "Nenhuma planilha Estratégico foi enviada e o arquivo padrão "
                f"não foi encontrado em {PLANILHA_PADRAO}."
            )
        itens = consolidar.ler_pedido(PLANILHA_PADRAO)
        origem_pedido = PLANILHA_PADRAO.name

    extrato = consolidar.ler_extrato(dados_extrato, nome_extrato)
    detectado = consolidar.detectar_colunas(extrato)
    mapa = dict(detectado)
    if mapa_manual:
        for campo in ("codigo", "estoque", "publico"):
            if campo in mapa_manual:
                mapa[campo] = mapa_manual[campo]

    # sem colunas suficientes, devolve a sessão para o usuário mapear à mão
    # em vez de recusar a requisição e deixá-lo sem saída
    incompleto = mapa.get("codigo") is None or (
        mapa.get("estoque") is None and mapa.get("publico") is None)
    if incompleto:
        ident = guardar_sessao({
            "extrato": extrato,
            "dados_pedido": dados_pedido,
            "nome_pedido": nome_pedido,
            "acrescimo": acrescimo,
        })
        return {
            "id": ident,
            "precisaMapear": True,
            "origemPedido": origem_pedido,
            "nomeExtrato": nome_extrato,
            "cabecalhos": extrato.cabecalhos,
            "mapa": mapa,
            "detectado": detectado,
            "acrescimo": acrescimo,
            "mensagem": ("Não consegui identificar as colunas do extrato pelo "
                         "cabeçalho. Indique abaixo qual coluna é o código da "
                         "peça, o estoque e o preço público."),
        }

    estatisticas = consolidar.cruzar(itens, extrato, mapa)
    xlsx = consolidar.gerar_xlsx(itens, acrescimo, estatisticas)
    csv_bytes = consolidar.gerar_csv(itens, acrescimo)

    ident = guardar_sessao({
        "xlsx": xlsx,
        "csv": csv_bytes,
        "extrato": extrato,
        "dados_pedido": dados_pedido,
        "nome_pedido": nome_pedido,
        "acrescimo": acrescimo,
    })

    return {
        "id": ident,
        "precisaMapear": False,
        "origemPedido": origem_pedido,
        "nomeExtrato": nome_extrato,
        "cabecalhos": extrato.cabecalhos,
        "mapa": mapa,
        "detectado": detectado,
        "acrescimo": acrescimo,
        "estatisticas": estatisticas,
        "itens": consolidar.itens_para_json(itens, acrescimo),
    }


# --------------------------------------------------------------------------- #
# HTTP                                                                        #
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "ConsolidadorVW/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------ utilitários ------------------------------ #
    def _responder(self, codigo: int, corpo: bytes, tipo: str, extra: dict | None = None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for chave, valor in (extra or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, codigo: int, dados: dict):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self._responder(codigo, corpo, "application/json; charset=utf-8")

    def _erro(self, codigo: int, mensagem: str):
        self._json(codigo, {"erro": mensagem})

    def _ler_corpo(self) -> bytes | None:
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._erro(400, "Content-Length inválido.")
            return None
        if tamanho <= 0:
            self._erro(400, "Requisição sem corpo.")
            return None
        if tamanho > TAMANHO_MAXIMO:
            self._erro(413, f"Arquivo maior que o limite de "
                            f"{TAMANHO_MAXIMO // (1024 * 1024)} MB.")
            return None
        return self.rfile.read(tamanho)

    def log_message(self, formato, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} "
              f"{formato % args}", flush=True)

    # --------------------------------- GET ---------------------------------- #
    def do_GET(self):
        caminho = urlparse(self.path).path

        if caminho in ("/", "/index.html"):
            arquivo = BASE / "index.html"
            if not arquivo.exists():
                return self._erro(500, "index.html não encontrado ao lado de app.py.")
            return self._responder(200, arquivo.read_bytes(),
                                   "text/html; charset=utf-8")

        if caminho == "/api/status":
            return self._json(200, {
                "ok": True,
                "planilhaPadrao": PLANILHA_PADRAO.name if PLANILHA_PADRAO.exists() else None,
                "limiteMB": TAMANHO_MAXIMO // (1024 * 1024),
            })

        if caminho.startswith("/api/baixar/"):
            return self._baixar(caminho)

        return self._erro(404, "Rota não encontrada.")

    def do_HEAD(self):
        self.do_GET()

    def _baixar(self, caminho: str):
        resto = caminho[len("/api/baixar/"):]
        if "." not in resto:
            return self._erro(400, "Formato não informado.")
        ident, _, formato = resto.rpartition(".")
        sessao = obter_sessao(ident)
        if not sessao:
            return self._erro(404, "Resultado expirado. Envie o extrato novamente.")

        if "xlsx" not in sessao:
            return self._erro(409, "Este resultado ainda não foi gerado. "
                                   "Confira as colunas e reprocesse.")

        if formato == "xlsx":
            corpo = sessao["xlsx"]
            tipo = ("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet")
            nome = "Estrategico_VW_Consolidado.xlsx"
        elif formato == "csv":
            corpo = sessao["csv"]
            tipo = "text/csv; charset=utf-8"
            nome = "Estrategico_VW_Consolidado.csv"
        else:
            return self._erro(400, "Formato deve ser xlsx ou csv.")

        return self._responder(200, corpo, tipo,
                               {"Content-Disposition": f'attachment; filename="{nome}"'})

    # --------------------------------- POST --------------------------------- #
    def do_POST(self):
        caminho = urlparse(self.path).path
        if caminho == "/api/processar":
            return self._processar()
        if caminho == "/api/remapear":
            return self._remapear()
        return self._erro(404, "Rota não encontrada.")

    def _processar(self):
        corpo = self._ler_corpo()
        if corpo is None:
            return
        try:
            campos = parse_multipart(corpo, self.headers.get("Content-Type", ""))
        except ValueError as exc:
            return self._erro(400, str(exc))

        extrato = campos.get("extrato")
        if not isinstance(extrato, dict) or not extrato.get("dados"):
            return self._erro(400, "Envie o extrato do DataLake (CSV ou XLSX).")

        pedido = campos.get("pedido")
        dados_pedido = pedido.get("dados") if isinstance(pedido, dict) else None
        nome_pedido = pedido.get("nome") if isinstance(pedido, dict) else None
        if dados_pedido is not None and not dados_pedido:
            dados_pedido = None

        acrescimo = consolidar.parse_numero(campos.get("acrescimo"))
        acrescimo = consolidar.ACRESCIMO_PADRAO if acrescimo is None else acrescimo / 100

        try:
            resultado = processar(extrato["dados"], extrato["nome"],
                                  dados_pedido, nome_pedido, acrescimo)
        except ValueError as exc:
            return self._erro(400, str(exc))
        except Exception as exc:                                  # noqa: BLE001
            self.log_message("erro ao processar: %r", exc)
            return self._erro(500, f"Falha ao processar os arquivos: {exc}")
        return self._json(200, resultado)

    def _remapear(self):
        corpo = self._ler_corpo()
        if corpo is None:
            return
        try:
            pedido_json = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._erro(400, "Corpo JSON inválido.")

        sessao = obter_sessao(pedido_json.get("id", ""))
        if not sessao:
            return self._erro(404, "Resultado expirado. Envie o extrato novamente.")

        extrato = sessao["extrato"]
        mapa = {campo: _indice(pedido_json.get(campo), extrato.cabecalhos)
                for campo in ("codigo", "estoque", "publico")}

        acrescimo = consolidar.parse_numero(pedido_json.get("acrescimo"))
        acrescimo = sessao["acrescimo"] if acrescimo is None else acrescimo / 100

        import io
        try:
            if sessao["dados_pedido"]:
                itens = consolidar.ler_pedido(io.BytesIO(sessao["dados_pedido"]))
            else:
                itens = consolidar.ler_pedido(PLANILHA_PADRAO)
            estatisticas = consolidar.cruzar(itens, extrato, mapa)
            xlsx = consolidar.gerar_xlsx(itens, acrescimo, estatisticas)
            csv_bytes = consolidar.gerar_csv(itens, acrescimo)
        except ValueError as exc:
            return self._erro(400, str(exc))
        except Exception as exc:                                  # noqa: BLE001
            self.log_message("erro ao remapear: %r", exc)
            return self._erro(500, f"Falha ao reprocessar: {exc}")

        ident = guardar_sessao({
            "xlsx": xlsx,
            "csv": csv_bytes,
            "extrato": extrato,
            "dados_pedido": sessao["dados_pedido"],
            "nome_pedido": sessao["nome_pedido"],
            "acrescimo": acrescimo,
        })
        return self._json(200, {
            "id": ident,
            "cabecalhos": extrato.cabecalhos,
            "mapa": mapa,
            "acrescimo": acrescimo,
            "estatisticas": estatisticas,
            "itens": consolidar.itens_para_json(itens, acrescimo),
        })


# --------------------------------------------------------------------------- #
# Inicialização                                                               #
# --------------------------------------------------------------------------- #
def ip_local() -> str:
    """Descobre o IP da máquina na rede (sem depender de DNS)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def preparar_console():
    """
    Evita UnicodeEncodeError no console do Windows.

    O terminal do Windows costuma usar cp850/cp1252, que não tem alguns dos
    caracteres das mensagens; sem isto o servidor quebraria ao imprimir.
    """
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main():
    preparar_console()
    parser = argparse.ArgumentParser(description="Consolidador Estratégico VW")
    parser.add_argument("--host", default="0.0.0.0",
                        help="endereço de escuta (padrão: 0.0.0.0, toda a rede)")
    parser.add_argument("--porta", type=int, default=8000,
                        help="porta HTTP (padrão: 8000)")
    args = parser.parse_args()

    mimetypes.init()
    servidor = ThreadingHTTPServer((args.host, args.porta), Handler)
    servidor.daemon_threads = True

    print("Consolidador Estratégico VW")
    print(f"  local ...... http://127.0.0.1:{args.porta}")
    if args.host == "0.0.0.0":
        print(f"  na rede .... http://{ip_local()}:{args.porta}")
    if PLANILHA_PADRAO.exists():
        print(f"  planilha base: {PLANILHA_PADRAO.name}")
    else:
        print("  planilha base: nao encontrada - envie a Estrategico pela pagina")
    print("  sem autenticação: use apenas na rede interna. Ctrl+C para parar.")

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
        servidor.shutdown()


if __name__ == "__main__":
    main()
