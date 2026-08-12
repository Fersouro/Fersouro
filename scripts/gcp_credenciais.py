#!/usr/bin/env python3
"""Carrega credenciais do GCP a partir de GCP_SA_KEY_B64 ou do ADC.

Extraido de list_buckets.py quando um segundo script passou a precisar da
mesma logica. A duplicacao seria pior que o acoplamento: e codigo que decide
com que identidade o projeto e acessado, e duas copias divergem em silencio.

Credenciais, na ordem de preferencia:

1. GCP_SA_KEY_B64  - chave JSON de service account codificada em base64.
   Decodificada em memoria; nunca e escrita em disco nem impressa.
2. GOOGLE_APPLICATION_CREDENTIALS ou Application Default Credentials.

Projeto: GOOGLE_CLOUD_PROJECT, ou o project_id embutido na credencial.
"""

from __future__ import annotations

import base64
import binascii
import json
import os

KEY_ENV = "GCP_SA_KEY_B64"
PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"

# Escopos usados pelos scripts do repositorio. Sao escopos amplos por
# exigencia da API — rodar uma query precisa de jobs.insert, que o escopo
# bigquery.readonly nao cobre. Quem limita o acesso a leitura e o papel IAM
# da service account, nao o escopo.
ESCOPO_STORAGE_RO = "https://www.googleapis.com/auth/devstorage.read_only"
ESCOPO_BIGQUERY = "https://www.googleapis.com/auth/bigquery"


class SetupError(RuntimeError):
    """Erro de configuracao que o usuario precisa corrigir antes de rodar."""


def carregar_chave():
    """Decodifica a chave da service account a partir de GCP_SA_KEY_B64.

    Retorna None se a variavel nao estiver definida, para que o chamador possa
    cair no fluxo de Application Default Credentials.
    """
    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        return None

    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SetupError(
            f"{KEY_ENV} nao e base64 valido ({exc}). Gere de novo com:\n"
            "  base64 -w0 chave.json"
        ) from exc

    try:
        info = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise SetupError(
            f"{KEY_ENV} decodificou, mas o conteudo nao e JSON ({exc}). "
            "Confirme que voce codificou o arquivo de chave inteiro."
        ) from exc

    missing = [f for f in ("client_email", "private_key", "project_id") if f not in info]
    if missing:
        raise SetupError(
            f"A chave em {KEY_ENV} nao tem os campos: {', '.join(missing)}. "
            "Isso normalmente indica que o JSON nao e uma chave de service account."
        )

    return info


def obter_credenciais(escopos: list[str], project: str | None = None):
    """Devolve (credentials, projeto, identidade) para os escopos pedidos."""
    from google.oauth2 import service_account

    info = carregar_chave()

    if info is not None:
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=escopos
        )
        project = project or info["project_id"]
        identity = info["client_email"]
    else:
        import google.auth

        try:
            credentials, default_project = google.auth.default(scopes=escopos)
        except Exception as exc:
            raise SetupError(
                f"Nenhuma credencial encontrada. Defina {KEY_ENV} com a chave da "
                "service account em base64 (veja docs/GCP_SETUP.md), ou configure "
                "Application Default Credentials.\n"
                f"Detalhe: {exc}"
            ) from exc
        project = project or default_project
        identity = getattr(credentials, "service_account_email", "ADC")

    if not project:
        raise SetupError(
            f"Projeto nao definido. Passe --project ou defina {PROJECT_ENV}."
        )

    return credentials, project, identity
