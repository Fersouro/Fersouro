#!/bin/bash
# Prepara o ambiente Python usado por scripts/list_buckets.py.
#
# O contêiner das sessões remotas é efêmero e recriado a cada sessão, então
# as dependências precisam ser reinstaladas aqui. Usamos um virtualenv porque
# o `cryptography` instalado no sistema quebra ao ser importado
# (pyo3_runtime.PanicException), e o google-auth depende dele.
set -euo pipefail

# Em máquinas locais o ambiente costuma já estar montado; só rodamos na web.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VENV="$PROJECT_DIR/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

# --upgrade mantém o passo idempotente e aproveita o cache do contêiner.
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet --upgrade -r "$PROJECT_DIR/requirements.txt"

# Deixa o venv na frente do PATH pelo resto da sessão.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

echo "session-start: venv pronto em $VENV"
