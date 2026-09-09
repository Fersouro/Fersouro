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


# ------------------------------------------------------------------- login


def test_senha_gravada_com_hash_e_sal_unico(tmp_path):
    """A senha nunca vai em claro para o arquivo, e dois usuarios com a mesma
    senha tem hash diferente."""
    arquivo = tmp_path / "usuarios.json"
    servir.gravar_usuario(arquivo, "Fernando", "senha-boa")
    servir.gravar_usuario(arquivo, "maria", "senha-boa")

    bruto = arquivo.read_text(encoding="utf-8")
    assert "senha-boa" not in bruto

    usuarios = servir.carregar_usuarios(arquivo)
    assert set(usuarios) == {"fernando", "maria"}          # nome normalizado
    assert usuarios["fernando"]["sal"] != usuarios["maria"]["sal"]
    assert usuarios["fernando"]["hash"] != usuarios["maria"]["hash"]


def test_senha_confere_so_com_a_senha_certa(tmp_path):
    arquivo = tmp_path / "usuarios.json"
    servir.gravar_usuario(arquivo, "fernando", "senha-boa")
    registro = servir.carregar_usuarios(arquivo)["fernando"]
    assert servir.senha_confere(registro, "senha-boa")
    assert not servir.senha_confere(registro, "senha-boA")
    assert not servir.senha_confere(registro, "")


def test_registro_corrompido_nao_deixa_entrar():
    assert not servir.senha_confere({}, "qualquer")
    assert not servir.senha_confere({"sal": "zz", "hash": "x"}, "qualquer")


def test_arquivo_de_usuarios_ausente_ou_quebrado(tmp_path):
    assert servir.carregar_usuarios(tmp_path / "nao_existe.json") == {}
    quebrado = tmp_path / "u.json"
    quebrado.write_text("{isso nao e json", encoding="utf-8")
    assert servir.carregar_usuarios(quebrado) == {}


def test_sessao_vale_ate_expirar():
    sessoes = servir.Sessoes()
    token = sessoes.criar("fernando")
    assert sessoes.usuario(token) == "fernando"
    assert sessoes.usuario("token-inventado") is None
    assert sessoes.usuario(None) is None

    sessoes.encerrar(token)
    assert sessoes.usuario(token) is None      # sair invalida no servidor


def test_sessao_expirada_nao_vale():
    sessoes = servir.Sessoes(horas=0)
    assert sessoes.usuario(sessoes.criar("fernando")) is None


def test_bloqueio_depois_de_cinco_falhas():
    sessoes = servir.Sessoes()
    for _ in range(servir.MAX_TENTATIVAS - 1):
        sessoes.registrar_falha("10.0.0.9")
    assert not sessoes.bloqueado("10.0.0.9")
    sessoes.registrar_falha("10.0.0.9")
    assert sessoes.bloqueado("10.0.0.9")
    assert not sessoes.bloqueado("10.0.0.10")      # bloqueio e por IP

    sessoes.limpar_falhas("10.0.0.9")              # acertou a senha, zera
    assert not sessoes.bloqueado("10.0.0.9")


def test_destino_do_login_nao_sai_do_servidor():
    """'//site.externo' num redirect depois do login vira phishing."""
    seguro = servir.Handler._destino_seguro
    assert seguro(None, "/relatorios/") == "/relatorios/"
    assert seguro(None, "//evil.com") == "/"
    assert seguro(None, "https://evil.com") == "/"
    assert seguro(None, "") == "/"


def test_pagina_de_login_nao_vaza_html_do_erro():
    corpo = servir.pagina_login("/", "<script>alerta()</script>")
    assert "<script>alerta()</script>" not in corpo
    assert "&lt;script&gt;" in corpo


def test_usuario_novo_vale_sem_reiniciar(tmp_path):
    """Cadastrar alguem com o servico no ar tem que valer na hora.

    Era o defeito de 09/09/2026: a lista era lida uma vez, na subida, e quem
    fosse cadastrado depois recebia 'usuario ou senha invalidos' com a senha
    certa.
    """
    arquivo = tmp_path / "usuarios.json"
    servir.gravar_usuario(arquivo, "fernando", "senha-boa")

    leitor = servir.ArquivoUsuarios(arquivo)
    assert set(leitor.atuais()) == {"fernando"}

    servir.gravar_usuario(arquivo, "maria", "outra-senha")
    assert set(leitor.atuais()) == {"fernando", "maria"}      # sem reiniciar nada


def test_troca_de_senha_vale_sem_reiniciar(tmp_path):
    arquivo = tmp_path / "usuarios.json"
    servir.gravar_usuario(arquivo, "fernando", "antiga")
    leitor = servir.ArquivoUsuarios(arquivo)
    assert servir.senha_confere(leitor.atuais()["fernando"], "antiga")

    servir.gravar_usuario(arquivo, "fernando", "nova")
    registro = leitor.atuais()["fernando"]
    assert servir.senha_confere(registro, "nova")
    assert not servir.senha_confere(registro, "antiga")


def test_arquivo_de_usuarios_sumindo_nao_quebra(tmp_path):
    arquivo = tmp_path / "usuarios.json"
    servir.gravar_usuario(arquivo, "fernando", "senha-boa")
    leitor = servir.ArquivoUsuarios(arquivo)
    assert leitor.atuais()
    arquivo.unlink()
    assert leitor.atuais() == {}          # ninguem entra, mas o servidor segue de pe
