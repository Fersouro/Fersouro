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
ERRLOG="$OUT/erros.log"
: > "$ERRLOG"

# Executa uma query e devolve JSON. Ao contrário da versão anterior, NÃO
# engole o erro: registra em erros.log e sinaliza a falha pelo código de
# retorno, para que o relatório nunca confunda "falhou" com "vazio".
q() {
  local sql="$1" loc="$2" out="$3" label="$4"
  if bq query --project_id="$PROJ" --location="$loc" --use_legacy_sql=false \
       --format=json --max_rows=100000 --quiet "$sql" > "$out" 2>>"$ERRLOG"; then
    # Query pode ter sucesso e retornar vazio; ambos são resultados válidos.
    [ -s "$out" ] || echo '[]' > "$out"
    return 0
  fi
  echo "--- FALHA em [$label] ---" >> "$ERRLOG"
  echo '[]' > "$out"
  return 1
}

{
  echo "# Metadados do BigQuery — \`$PROJ\`"
  echo
  echo "Gerado em $(date -Iseconds)"
  echo
} > "$REPORT"

FALHAS=0

for DS in "${DATASETS[@]}"; do
  echo "== dataset: $DS" >&2
  mkdir -p "$OUT/$DS/views" "$OUT/$DS/schemas"

  echo "## Dataset \`$DS\`" >> "$REPORT"
  echo >> "$REPORT"

  # --- Preflight: o dataset existe e em que região? ------------------------
  # Região errada é a causa mais comum de INFORMATION_SCHEMA falhar: o bq
  # assume US por padrão, mas o dataset pode estar em southamerica-east1.
  echo "  verificando acesso e região..." >&2
  if ! bq show --project_id="$PROJ" --format=json "$PROJ:$DS" \
        > "$OUT/$DS/dataset.json" 2>>"$ERRLOG"; then
    {
      echo "> **Dataset inacessível.** Não foi possível ler \`$PROJ:$DS\`."
      echo "> Veja \`erros.log\`. Causas comuns: nome incorreto, projeto"
      echo "> errado, ou falta de permissão (\`roles/bigquery.metadataViewer\`)."
      echo
    } >> "$REPORT"
    FALHAS=$((FALHAS + 1))
    continue
  fi

  LOC="$(python3 - "$OUT/$DS/dataset.json" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("location") or "US")
except Exception:
    print("US")
PY
)"
  echo "  região: $LOC" >&2
  echo "Região: \`$LOC\`" >> "$REPORT"
  echo >> "$REPORT"

  # --- Classificação: nativa vs externa vs view ----------------------------
  echo "  classificando tabelas..." >&2
  TIPOS_OK=1
  q "SELECT table_type, COUNT(*) AS n
     FROM \`$PROJ.$DS.INFORMATION_SCHEMA.TABLES\`
     GROUP BY table_type ORDER BY n DESC" \
    "$LOC" "$OUT/$DS/tipos.json" "tipos/$DS" || TIPOS_OK=0

  {
    echo "### Composição"
    echo
    if [ "$TIPOS_OK" -eq 0 ]; then
      echo "> **Consulta falhou** — veja \`erros.log\`. Nada abaixo pode ser"
      echo "> concluído sobre este dataset."
      FALHAS=$((FALHAS + 1))
    else
      python3 - "$OUT/$DS/tipos.json" <<'PY'
import json, sys
try:
    rows = json.load(open(sys.argv[1]))
except Exception:
    rows = []
if not rows:
    print("> Consulta bem-sucedida, mas o dataset nao tem tabelas.")
else:
    print("| Tipo | Quantidade |")
    print("| --- | --- |")
    for r in rows:
        print("| {} | {} |".format(r.get("table_type", "?"), r.get("n", "?")))
PY
    fi
    echo
  } >> "$REPORT"

  [ "$TIPOS_OK" -eq 0 ] && continue

  # --- Tamanho real do storage nativo -------------------------------------
  # __TABLES__ é uma metatabela por dataset e devolve size_bytes/row_count
  # direto. Usamos ela em vez de INFORMATION_SCHEMA.TABLE_STORAGE porque
  # aquela view é escopada por REGIÃO (region-southamerica-east1.…), não por
  # dataset — qualificá-la como dataset falha sempre.
  echo "  medindo storage..." >&2
  ST_OK=1
  q "SELECT
       COALESCE(SUM(size_bytes), 0) AS bytes,
       COALESCE(SUM(row_count), 0)  AS linhas,
       COUNT(*)                     AS tabelas
     FROM \`$PROJ.$DS.__TABLES__\`" \
    "$LOC" "$OUT/$DS/storage.json" "storage/$DS" || ST_OK=0

  {
    echo "### Storage nativo"
    echo
    if [ "$ST_OK" -eq 0 ]; then
      echo "> **Consulta falhou** — veja \`erros.log\`. Tamanho desconhecido."
    else
      python3 - "$OUT/$DS/storage.json" <<'PY'
import json, sys
try:
    r = json.load(open(sys.argv[1]))[0]
except Exception:
    print("> Consulta retornou vazio.")
    raise SystemExit
b = int(r.get("bytes") or 0)
print("- Bytes: {:,} ({:.2f} GiB)".format(b, b / 1024 ** 3))
print("- Linhas: {:,}".format(int(r.get("linhas") or 0)))
print("- Tabelas com storage: {}".format(r.get("tabelas")))
PY
    fi
    echo
  } >> "$REPORT"

  # --- DDL completo de tudo ------------------------------------------------
  echo "  extraindo DDL..." >&2
  DDL_OK=1
  q "SELECT table_name, table_type, ddl
     FROM \`$PROJ.$DS.INFORMATION_SCHEMA.TABLES\`
     ORDER BY table_name" \
    "$LOC" "$OUT/$DS/ddl.json" "ddl/$DS" || DDL_OK=0

  if [ "$DDL_OK" -eq 1 ]; then
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
  fi

  # --- Origens externas ----------------------------------------------------
  # Só afirma algo se o DDL foi realmente extraído. Ausência de arquivo NÃO
  # é evidência de tabela nativa.
  {
    echo "### Origens externas referenciadas"
    echo
    if [ "$DDL_OK" -eq 0 ]; then
      echo "> **DDL não extraído** — impossível dizer se são nativas ou externas."
      FALHAS=$((FALHAS + 1))
    elif [ -z "$(ls -A "$OUT/$DS/schemas" 2>/dev/null)" ]; then
      echo "> Nenhum DDL de tabela retornado — nada a classificar."
    else
      URIS="$(grep -rhoE 'gs://[A-Za-z0-9._/-]+' "$OUT/$DS/schemas" 2>/dev/null \
              | sed -E 's#(gs://[^/]+/[^/]*).*#\1#' | sort -u | head -20 || true)"
      if [ -z "$URIS" ]; then
        echo "Nenhuma URI \`gs://\` em $(ls "$OUT/$DS/schemas" | wc -l) DDLs"
        echo "inspecionados — as tabelas são **nativas**."
      else
        echo '```'
        echo "$URIS"
        echo '```'
      fi
    fi
    echo
  } >> "$REPORT"
done

echo >&2
if [ "$FALHAS" -gt 0 ]; then
  echo "CONCLUÍDO COM $FALHAS FALHA(S). Veja: $ERRLOG" >&2
  echo "Não tire conclusões do relatório sem antes resolver os erros." >&2
else
  echo "concluído sem erros." >&2
fi
echo "relatório: $REPORT" >&2
echo >&2
echo "ATENÇÃO: as views em $OUT/*/views/ contêm lógica de negócio." >&2
echo "NÃO faça commit disso em repositório público. Guarde num repo" >&2
echo "privado ou baixe para uma máquina sua." >&2
[ "$FALHAS" -gt 0 ] && exit 1 || exit 0
