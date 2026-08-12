#!/usr/bin/env python3
"""Lista os buckets do Cloud Storage de um projeto GCP.

Substitui o caminho manual no Console (busca "Cloud Storage" -> "Buckets")
por uma chamada direta a API, para que a lista possa ser obtida de dentro de
uma sessao do Claude Code, que nao tem navegador autenticado.

Credenciais, na ordem de preferencia:

1. GCP_SA_KEY_B64  - chave JSON de service account codificada em base64.
   Decodificada em memoria; nunca e escrita em disco nem impressa.
2. GOOGLE_APPLICATION_CREDENTIALS ou Application Default Credentials.

Projeto: GOOGLE_CLOUD_PROJECT, ou o project_id embutido na credencial.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys

READ_ONLY_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"
KEY_ENV = "GCP_SA_KEY_B64"
PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"


class SetupError(RuntimeError):
    """Erro de configuracao que o usuario precisa corrigir antes de rodar."""


def _load_key_from_env():
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


def _build_client(project: str | None):
    """Monta um client do Cloud Storage e devolve (client, projeto, identidade)."""
    from google.cloud import storage
    from google.oauth2 import service_account

    info = _load_key_from_env()

    if info is not None:
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=[READ_ONLY_SCOPE]
        )
        project = project or info["project_id"]
        identity = info["client_email"]
    else:
        import google.auth

        try:
            credentials, default_project = google.auth.default(scopes=[READ_ONLY_SCOPE])
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

    return storage.Client(project=project, credentials=credentials), project, identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default=os.environ.get(PROJECT_ENV),
        help=f"ID do projeto GCP (padrao: ${PROJECT_ENV} ou o da credencial)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emite JSON em vez de texto"
    )
    parser.add_argument(
        "--long",
        action="store_true",
        help="Mostra tambem localizacao e classe de armazenamento",
    )
    args = parser.parse_args()

    try:
        client, project, identity = _build_client(args.project)
        buckets = sorted(client.list_buckets(), key=lambda b: b.name)
    except SetupError as exc:
        print(f"erro de configuracao: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Erros de permissao sao o caso comum aqui e merecem uma dica acionavel.
        print(f"erro ao chamar a API do Cloud Storage: {exc}", file=sys.stderr)
        if "403" in str(exc) or "permission" in str(exc).lower():
            print(
                "\nA credencial autenticou mas nao pode listar buckets. Conceda "
                "roles/storage.bucketViewer no projeto (veja docs/GCP_SETUP.md).",
                file=sys.stderr,
            )
        return 1

    if args.json:
        payload = [
            {"name": b.name, "location": b.location, "storage_class": b.storage_class}
            for b in buckets
        ]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"projeto: {project}", file=sys.stderr)
    print(f"identidade: {identity}", file=sys.stderr)
    print(f"buckets: {len(buckets)}\n", file=sys.stderr)

    if not buckets:
        print("(nenhum bucket neste projeto)", file=sys.stderr)
        return 0

    for bucket in buckets:
        if args.long:
            print(f"{bucket.name}\t{bucket.location}\t{bucket.storage_class}")
        else:
            print(bucket.name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
