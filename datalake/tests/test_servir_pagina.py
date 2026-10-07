"""Servidor da pagina: argumentos e certificado.

O script vive em scripts/ (nao e pacote), entao o teste o carrega pelo caminho.
"""

from __future__ import annotations

import datetime as dt
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


# ------------------------------------------------------------------ gerador


def _projeto_falso(tmp_path, yml):
    projeto = tmp_path / "app" / "Fersouro-x" / "datalake"
    (projeto / "conf" / "reports").mkdir(parents=True)
    (projeto / "pyproject.toml").write_text("[project]\nname='datalake'\n", encoding="utf-8")
    (projeto / "conf" / "reports" / "10_teste.yml").write_text(yml, encoding="utf-8")
    return projeto


def test_acha_o_projeto_dentro_de_app(tmp_path):
    projeto = _projeto_falso(tmp_path, "name: teste\nsheets:\n  - name: A\n    sql: SELECT 1\n")
    assert servir.achar_projeto(str(tmp_path)) == str(projeto)


def test_sem_projeto_a_pagina_nao_quebra(tmp_path):
    assert servir.achar_projeto(str(tmp_path)) is None
    corpo = servir.pagina_gerador("fernando", [], None)
    assert "Nao encontrei o projeto" in corpo


def test_le_nome_titulo_e_parametros_do_yaml(tmp_path):
    """O servico roda com o Python do sistema, que pode nao ter pyyaml."""
    projeto = _projeto_falso(tmp_path, """
name: faturamento-funilaria
title: Faturamento-Funilaria
description: Notas de servico da funilaria.
parameters:
  - name: competencia
    label: Competencia
    type: mes
    default: atual
  - name: departamento
    label: Departamento
    type: numero
    default: 410
    optional: true
sheets:
  - name: Mes atual
    sql: SELECT 1
""")
    (relatorio,) = servir.relatorios_disponiveis(str(projeto))
    assert relatorio["name"] == "faturamento-funilaria"
    assert relatorio["title"] == "Faturamento-Funilaria"
    assert [p["name"] for p in relatorio["parameters"]] == ["competencia", "departamento"]
    assert relatorio["parameters"][1]["optional"] is True
    assert relatorio["parameters"][0]["default"] == "atual"


def test_yaml_sem_parametros(tmp_path):
    projeto = _projeto_falso(tmp_path, "name: estoque\ntitle: Estoque\nsheets:\n  - name: A\n    sql: SELECT 1\n")
    (relatorio,) = servir.relatorios_disponiveis(str(projeto))
    assert relatorio["parameters"] == []


def test_formulario_traz_o_mes_corrente_preenchido(tmp_path):
    projeto = _projeto_falso(tmp_path, """
name: r
title: Relatorio
parameters:
  - name: competencia
    label: Competencia
    type: mes
    default: atual
sheets:
  - name: A
    sql: SELECT 1
""")
    corpo = servir.pagina_gerador("fernando", servir.relatorios_disponiveis(str(projeto)), str(projeto))
    assert dt.date.today().strftime("%Y-%m") in corpo
    assert "name='p_competencia'" in corpo


def test_pagina_do_gerador_escapa_o_que_vem_de_fora(tmp_path):
    corpo = servir.pagina_gerador("fernando", [], "/x", pronto="<script>x</script>.xlsx",
                                  erro="<script>y</script>")
    assert "<script>" not in corpo
    assert "&lt;script&gt;" in corpo


def test_data_no_formulario_sai_em_dd_mm_aaaa():
    """01/08/2026 e como a data se escreve aqui -- e o servidor aceita assim."""
    hoje = dt.date.today()
    assert servir._padrao_visivel("data", "inicio-do-mes") == hoje.replace(day=1).strftime("%d/%m/%Y")
    assert servir._padrao_visivel("data", "hoje") == hoje.strftime("%d/%m/%Y")
    assert servir._padrao_visivel("data", "2026-08-30") == "30/08/2026"
    assert servir._padrao_visivel("data", "30/08/2026") == "30/08/2026"


def test_fim_do_mes_no_formulario_em_dezembro(monkeypatch):
    class Dezembro(dt.date):
        @classmethod
        def today(cls):
            return dt.date(2026, 12, 7)

    monkeypatch.setattr(servir.datetime, "date", Dezembro)
    assert servir._padrao_visivel("data", "fim-do-mes") == "31/12/2026"


def test_layout_e_lista_com_botao_de_exportar(tmp_path):
    projeto = _projeto_falso(tmp_path, """
name: r
title: Relatorio
parameters:
  - name: data_inicial
    label: Data inicial
    type: data
    default: inicio-do-mes
  - name: data_final
    label: Data final
    type: data
    default: fim-do-mes
sheets:
  - name: A
    sql: SELECT 1
""")
    corpo = servir.pagina_gerador("fernando", servir.relatorios_disponiveis(str(projeto)),
                                  str(projeto))
    assert "Exportar em Excel" in corpo
    assert "class=\"lista\"" in corpo and "class=\"linha\"" in corpo   # um por linha
    assert "grid-template-columns" not in corpo                        # nao e mais grade
    assert dt.date.today().replace(day=1).strftime("%d/%m/%Y") in corpo


def test_sem_usuario_o_servidor_explica_em_vez_de_nao_existir(tmp_path):
    """Sair na subida deixava a porta vazia: o navegador dizia so 'conexao
    recusada', que nao conta que faltava cadastrar alguem."""
    corpo = servir.pagina_sem_usuarios(str(tmp_path / "usuarios.json"))
    assert "Ninguém está cadastrado" in corpo
    assert "CADASTRAR-USUARIO.bat" in corpo
    assert "usuarios.json" in corpo


def test_scripts_sem_aviso_de_escape():
    """'C:\\Program Files' numa string comum vira escape invalido: o Python 3.12
    avisa e versoes futuras recusam."""
    import warnings

    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "scripts"
    for arquivo in sorted(raiz.glob("*.py")):
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            compile(arquivo.read_text(encoding="utf-8"), str(arquivo), "exec")
        assert not [a for a in avisos if issubclass(a.category, SyntaxWarning)], (
            f"{arquivo.name}: {[str(a.message) for a in avisos]}"
        )


def test_reserva_le_as_opcoes_do_campo_de_escolha(tmp_path):
    """Sem isto, um seletor virava caixa de texto justamente quando algo ja
    estava errado -- que foi como o problema apareceu na tela."""
    projeto = _projeto_falso(tmp_path, """
name: faturamento
title: Faturamento
parameters:
  - name: data_inicial
    label: Data inicial
    type: data
    default: inicio-do-mes
  - name: revenda
    label: Revenda
    type: lista
    default: ""
    optional: true
    options:
      - value: 1
        label: Revenda 1
      - value: 2
        label: Revenda 2
      - value: ""
        label: Consolidado (1 e 2)
sheets:
  - name: A
    sql: SELECT 1
""")
    (relatorio,) = servir._relatorios_do_yaml(str(projeto))
    campos = {p["name"]: p for p in relatorio["parameters"]}
    assert set(campos) == {"data_inicial", "revenda"}
    assert campos["data_inicial"]["options"] == []          # opcao de um nao vaza para o outro
    assert [(o["value"], o["label"]) for o in campos["revenda"]["options"]] == [
        ("1", "Revenda 1"), ("2", "Revenda 2"), ("", "Consolidado (1 e 2)")
    ]

    corpo = servir.pagina_gerador("fernando", [relatorio], str(projeto))
    assert "<select name='p_revenda'>" in corpo
    assert "Consolidado (1 e 2)" in corpo


def test_erro_de_varias_linhas_aparece_inteiro():
    """Erro de SQL termina numa linha com so '^'; mostrar a ultima linha deixava
    a tela com um acento circunflexo e nada mais."""
    erro = 'ParserException: syntax error at or near "$"\nLINE 1: SELECT ...\n        ^'
    corpo = servir.pagina_gerador("fernando", [], "/x", erro=erro)
    assert "<pre>" in corpo
    assert "syntax error" in corpo
    assert "LINE 1" in corpo
