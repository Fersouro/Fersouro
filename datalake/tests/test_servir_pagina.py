"""Servidor da pagina: argumentos e certificado.

O script vive em scripts/ (nao e pacote), entao o teste o carrega pelo caminho.
"""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "servir_pagina", Path(__file__).resolve().parents[1] / "scripts" / "servir_pagina.py"
)
servir = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(servir)


def _endereco(argv):
    o = servir.parse_args(argv)
    porta = o["porta"] or (servir.PORTA_HTTPS if o["tls"] else servir.PORTA_HTTP)
    return ("https" if o["tls"] else "http"), o["host"], porta


def test_padrao_e_https_na_8443():
    assert _endereco([]) == ("https", "0.0.0.0", 8443)


def test_tarefa_antiga_continua_em_http(tmp_path):
    """A Tarefa Agendada registrada antes chama 'script 8080 <pasta>'.

    Virar HTTPS sozinho quebraria o link salvo de quem ja usa a pagina.
    """
    assert _endereco(["8080", str(tmp_path)]) == ("http", "0.0.0.0", 8080)
    assert servir.parse_args(["8080", str(tmp_path)])["redirecionar_de"] is None


def test_forma_antiga_com_https_explicito_muda_de_protocolo(tmp_path):
    assert _endereco(["8443", str(tmp_path), "--https"]) == ("https", "0.0.0.0", 8443)


def test_flags_do_instalador():
    argv = ["--porta", "8443", "--host", "192.168.78.6", "--redirecionar-de", "8080"]
    assert _endereco(argv) == ("https", "192.168.78.6", 8443)
    assert servir.parse_args(argv)["redirecionar_de"] == 8080


def test_http_explicito_desliga_o_tls():
    assert _endereco(["--http", "8080"]) == ("http", "0.0.0.0", 8080)


def test_sem_redirecionar():
    assert servir.parse_args(["--sem-redirecionar"])["redirecionar_de"] is None


def test_argumento_desconhecido_nao_sobe_servidor():
    assert servir.parse_args(["--nao-existe"]) is None


def test_certificado_cobre_o_ip_de_acesso(tmp_path):
    """Sem o IP no certificado o navegador reclama do nome mesmo apos aceitar."""
    x509 = pytest.importorskip("cryptography.x509")
    cert = tmp_path / "servidor.pem"
    ok, motivo = servir.gerar_certificado(cert, tmp_path / "servidor.key", extras=["192.168.78.6"])
    assert ok, motivo

    lido = x509.load_pem_x509_certificate(cert.read_bytes())
    san = lido.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    nomes = set(san.get_values_for_type(x509.DNSName))
    assert "192.168.78.6" in ips
    assert "127.0.0.1" in ips
    assert {"localhost", socket.gethostname()} <= nomes


def test_certificado_gera_par_de_arquivos_legiveis(tmp_path):
    pytest.importorskip("cryptography")
    cert, chave = tmp_path / "c.pem", tmp_path / "c.key"
    ok, _ = servir.gerar_certificado(cert, chave)
    assert ok
    assert cert.read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"PRIVATE KEY" in chave.read_bytes()
    assert servir.contexto_tls(cert, chave) is not None      # o ssl aceita o par
