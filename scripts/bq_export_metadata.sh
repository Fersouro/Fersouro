#!/bin/bash
# Extrai os METADADOS do BigQuery: classificação de tabelas, tamanhos e,
# principalmente, a definição SQL de cada view.
#
# SOMENTE LEITURA. Usa apenas SELECT sobre INFORMATION_SCHEMA.
#
# Por que isso existe separado do inventário: views não são dados. Exportar
# um dataset de views como se fossem tabelas materializa o resultado e perde
# o SQL que o produz — que costuma ser a lógica de negócio mais valiosa do
# datalake. Este script salva cada definição como um .sql versionável.
#
# Também responde a pergunta que decide o tamanho real da migração: as
# tabelas são NATIVAS (storage próprio do BigQuery, precisa exportar) ou
# EXTERNAS (apontam para arquivos no GCS, já cobertas pela cópia do bucket)?
#
# Uso:
#   ./scripts/bq_export_metadata.sh tterrasul-datalake lake gold
set -euo pipefail

PROJ="${1:-}"
shift || true
DATASETS=("$@")

if [ -z "$PROJ" ] || [ ${#DATASETS[@]} -eq 0 ]; then
  echo "uso: $0 PROJETO DATASET [DATASET...]" >&2
  echo "ex:  $0 tterrasul-datalake lake gold" >&2
  exit 2
fi

command -v bq >/dev/null 2>&1 || { echo "erro: 'bq' não encontrado." >&2; exit 2; }

OUT="metadados-bq-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
REPORT="$OUT/relatorio.md"

# bq query com saída JSON; falhas viram JSON vazio para não derrubar o script.
q() {
  bq query --project_id="$PROJ" --use_legacy_sql=false --format=json \
     --max_rows=100000 --quiet "$1" 2>/dev/null || echo '[]'
}

{
  echo "# Metadados do BigQuery — \`$PROJ\`"
  echo
  echo "Gerado em $(date -Iseconds)"
  echo
} > "$REPORT"

for DS in "${DATASETS[@]}"; do
  echo "== dataset: $DS" >&2
  mkdir -p "$OUT/$DS/views" "$OUT/$DS/schemas"

  # --- Classificação: nativa vs externa vs view ----------------------------
  echo "  classificando tabelas..." >&2
  q "SELECT table_type, COUNT(*) AS n
     FROM \`$PROJ.$DS.INFORMATION_SCHEMA.TABLES\`
     GROUP BY table_type ORDER BY n DESC" > "$OUT/$DS/tipos.json"

  {
    echo "## Dataset \`$DS\`"
    echo
    echo "### Composição"
    echo
    echo "| Tipo | Quantidade |"
    echo "| --- | --- |"
    python3 - "$OUT/$DS/tipos.json" <<'PY'
import json, sys
try:
    rows = json.load(open(sys.argv[1]))
except Exception:
    rows = []
for r in rows:
    print("| {} | {} |".format(r.get("table_type", "?"), r.get("n", "?")))
PY
    echo
  } >> "$REPORT"

  # --- Tamanho real do storage nativo -------------------------------------
  # Só tabelas nativas ocupam storage no BigQuery. Externas apontam para o
  # GCS e portanto já estão contempladas na cópia do bucket.
  echo "  medindo storage..." >&2
  q "SELECT
       COALESCE(SUM(total_logical_bytes), 0) AS bytes,
       COALESCE(SUM(total_rows), 0)          AS linhas,
       COUNT(*)                              AS tabelas
     FROM \`$PROJ.$DS.INFORMATION_SCHEMA.TABLE_STORAGE\`" > "$OUT/$DS/storage.json"

  {
    echo "### Storage nativo"
    echo
    python3 - "$OUT/$DS/storage.json" <<'PY'
import json, sys
try:
    r = json.load(open(sys.argv[1]))[0]
except Exception:
    print("_Nao foi possivel medir (permissao ou regiao)._")
    raise SystemExit
b = int(r.get("bytes") or 0)
print("- Bytes: {:,} ({:.2f} GiB)".format(b, b / 1024 ** 3))
print("- Linhas: {:,}".format(int(r.get("linhas") or 0)))
print("- Tabelas com storage: {}".format(r.get("tabelas")))
if b == 0:
    print()
    print("> Storage nativo zero: as tabelas sao EXTERNAS. Os dados vivem no")
    print("> GCS e ja estao cobertos pela copia do bucket.")
PY
    echo
  } >> "$REPORT"

  # --- DDL completo de tudo ------------------------------------------------
  # A coluna ddl reconstrói CREATE TABLE / CREATE EXTERNAL TABLE (incluindo
  # as URIs do GCS) / CREATE VIEW. É o que permite recriar tudo no destino.
  echo "  extraindo DDL..." >&2
  q "SELECT table_name, table_type, ddl
     FROM \`$PROJ.$DS.INFORMATION_SCHEMA.TABLES\`
     ORDER BY table_name" > "$OUT/$DS/ddl.json"

  python3 - "$OUT" "$DS" <<'PY'
import json, os, re, sys
out, ds = sys.argv[1], sys.argv[2]
try:
    rows = json.load(open(os.path.join(out, ds, "ddl.json")))
except Exception:
    rows = []
n_view = n_tab = 0
for r in rows:
    name = r.get("table_name") or "sem_nome"
    ddl = r.get("ddl") or ""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    is_view = "VIEW" in (r.get("table_type") or "")
    sub = "views" if is_view else "schemas"
    if is_view:
        n_view += 1
    else:
        n_tab += 1
    with open(os.path.join(out, ds, sub, safe + ".sql"), "w") as f:
        f.write(ddl if ddl.endswith("\n") else ddl + "\n")
sys.stderr.write("  {} views e {} tabelas salvas\n".format(n_view, n_tab))
PY

  # --- Amostra de URIs externas --------------------------------------------
  # Confirma para onde as tabelas externas apontam.
  URIS="$(grep -rhoE 'gs://[A-Za-z0-9._/-]+' "$OUT/$DS/schemas" 2>/dev/null \
          | sed -E 's#(gs://[^/]+/[^/]*).*#\1#' | sort -u | head -20 || true)"
  {
    echo "### Origens externas referenciadas"
    echo
    if [ -z "$URIS" ]; then
      echo "_Nenhuma URI \`gs://\` no DDL — tabelas são nativas._"
    else
      echo '```'
      echo "$URIS"
      echo '```'
    fi
    echo
  } >> "$REPORT"
done

echo >&2
echo "relatório: $REPORT" >&2
echo "views salvas como .sql — versione esse diretório, é a lógica de negócio." >&2
