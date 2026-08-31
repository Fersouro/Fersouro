#!/usr/bin/env bash
# Sobe o Consolidador Estratégico VW na rede local.
#   ./iniciar.sh          -> porta 8000
#   ./iniciar.sh 8080     -> porta 8080
set -euo pipefail
cd "$(dirname "$0")"
PORTA="${1:-8000}"
python3 -c "import openpyxl" 2>/dev/null || {
  echo "Instalando dependência (openpyxl)..."
  python3 -m pip install --quiet -r requirements.txt
}
exec python3 app.py --porta "$PORTA"
