#!/usr/bin/env python3
"""Lista os buckets do Cloud Storage de um projeto GCP.

Substitui o caminho manual no Console (busca "Cloud Storage" -> "Buckets")
por uma chamada direta a API, para que a lista possa ser obtida de dentro de
uma sessao do Claude Code, que nao tem navegador autenticado.

Credenciais e projeto: veja gcp_credenciais.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from gcp_credenciais import (
    ESCOPO_STORAGE_RO,
    PROJECT_ENV,
    SetupError,
    obter_credenciais,
)


def _build_client(project: str | None):
    """Monta um client do Cloud Storage e devolve (client, projeto, identidade)."""
    from google.cloud import storage

    credentials, project, identity = obter_credenciais([ESCOPO_STORAGE_RO], project)
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
