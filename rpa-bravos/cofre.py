# -*- coding: utf-8 -*-
"""Senha do BRAVOS no Gerenciador de Credenciais do Windows (via keyring).

    python cofre.py cadastrar   # pede a senha (sem mostrar) e guarda no cofre
    python cofre.py apagar      # remove do cofre

A senha fica cifrada pelo Windows, presa ao usuario que cadastrou. Nunca vai
para arquivo, log, print ou git. BRAVOS_PASSWORD (variavel de ambiente) so e
aceita como alternativa, sem nunca ser gravada.
"""
from __future__ import annotations

import getpass
import os
import sys

SERVICO = "rpa-bravos"


def senha(usuario: str) -> str | None:
    if os.environ.get("BRAVOS_PASSWORD"):
        return os.environ["BRAVOS_PASSWORD"]
    try:
        import keyring
        return keyring.get_password(SERVICO, usuario)
    except Exception:
        return None


def main() -> int:
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass
    import keyring
    usuario = os.environ.get("BRAVOS_USUARIO") or input("Usuario do BRAVOS: ").strip()
    acao = sys.argv[1] if len(sys.argv) > 1 else "cadastrar"
    if acao == "apagar":
        keyring.delete_password(SERVICO, usuario)
        print("Senha removida do cofre.")
        return 0
    s1 = getpass.getpass(f"Senha do BRAVOS para {usuario} (nao aparece na tela): ")
    s2 = getpass.getpass("Repita a senha: ")
    if not s1 or s1 != s2:
        print("As senhas nao conferem. Nada foi gravado.")
        return 1
    keyring.set_password(SERVICO, usuario, s1)
    print("Senha guardada no Gerenciador de Credenciais do Windows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
