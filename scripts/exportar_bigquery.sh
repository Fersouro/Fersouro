#!/bin/bash
# Fase 3 do BigQuery: exporta todas as tabelas nativas de um dataset.
#
# ATENÇÃO — este é o ÚNICO script do repositório que ESCREVE no GCP.
# O `bq extract` só sabe gravar em bucket do GCS; não existe caminho direto
# de tabela para disco local. Ele NÃO altera nem apaga nada do datalake:
# apenas cria arquivos novos no prefixo de staging que você indicar.
#
# Recomendação: use um bucket separado e descartável para o staging, para
# não misturar os arquivos exportados com os dados originais do datalake:
#
#   gcloud storage buckets create gs://SEU-STAGING --location=southamerica-east1
#
# Uso:
#   ./scripts/exportar_bigquery.sh tterrasul-datalake lake gs://SEU-STAGING/lake
set -euo pipefail

PROJ="${1:-}"
DS="${2:-}"
STAGING="${3:-}"
PARALELO="${PARALELO:-4}"

if [ -z "$PROJ" ] || [ -z "$DS" ] || [ -z "$STAGING" ]; then
  echo "uso: $0 PROJETO DATASET gs://STAGING/prefixo" >&2
  exit 2
fi

case "$STAGING" in
  gs://*) ;;
  *) echo "erro: staging precisa ser um caminho gs://" >&2; exit 2 ;;
esac

command -v bq >/dev/null 2>&1 || { echo "erro: 'bq' não encontrado." >&2; exit 2; }

if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q .; then
  echo "erro: nenhuma conta autenticada. Rode: gcloud auth login" >&2
  exit 2
fi

OUT="export-$DS-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
MANIFESTO="$OUT/manifesto.tsv"
FALHAS_LOG="$OUT/falhas.log"
: > "$FALHAS_LOG"

# --- Manifesto: a fonte da verdade para a verificação posterior ------------
# Guardamos row_count ANTES de exportar. É contra esse número que a fase 4
# vai conferir o que chegou no disco.
echo "levantando tabelas e contagens..."
bq query --project_id="$PROJ" --use_legacy_sql=false --format=csv --quiet \
   --max_rows=100000 \
   "SELECT table_id, row_count, size_bytes
    FROM \`$PROJ.$DS.__TABLES__\`
    WHERE type = 1
    ORDER BY table_id" 2>/dev/null | tail -n +2 | tr ',' '\t' > "$MANIFESTO"

N="$(wc -l < "$MANIFESTO" | tr -d ' ')"
if [ "$N" -eq 0 ]; then
  echo "erro: nenhuma tabela encontrada em $PROJ.$DS" >&2
  exit 1
fi

TOTAL_BYTES="$(awk -F'\t' '{s+=$3} END {print s+0}' "$MANIFESTO")"
echo "  $N tabelas, $TOTAL_BYTES bytes"
echo "  staging: $STAGING"
echo "  paralelismo: $PARALELO"
echo

# --- Exportação ------------------------------------------------------------
# Parquet preserva tipos e estruturas aninhadas; CSV não. O sufixo *.parquet
# é obrigatório porque tabelas grandes são fatiadas em vários arquivos pelo
# próprio BigQuery, e o curinga é como ele nomeia os pedaços.
exportar_uma() {
  local tabela="$1" proj="$2" ds="$3" staging="$4" out="$5"
  local destino="$staging/$tabela/*.parquet"

  # Idempotente: se já existe arquivo para essa tabela, não refaz.
  if gcloud storage ls "$staging/$tabela/" >/dev/null 2>&1; then
    echo "  [pulado] $tabela (já exportado)"
    return 0
  fi

  if bq extract --project_id="$proj" --destination_format=PARQUET \
       "$proj:$ds.$tabela" "$destino" >/dev/null 2>>"$out/falhas.log"; then
    echo "  [ok] $tabela"
  else
    echo "  [FALHOU] $tabela"
    echo "$tabela" >> "$out/tabelas_com_falha.txt"
  fi
}
export -f exportar_uma

echo "exportando (isto leva alguns minutos)..."
cut -f1 "$MANIFESTO" \
  | xargs -P "$PARALELO" -I{} bash -c \
      'exportar_uma "$@"' _ {} "$PROJ" "$DS" "$STAGING" "$OUT" \
  | tee "$OUT/progresso.log"

# --- Resultado -------------------------------------------------------------
N_FALHAS=0
[ -f "$OUT/tabelas_com_falha.txt" ] && \
  N_FALHAS="$(wc -l < "$OUT/tabelas_com_falha.txt" | tr -d ' ')"

# grep -c ja imprime 0 quando nao ha match, mas sai com codigo 1; usar
# '|| echo 0' duplicaria o valor. Por isso '|| true'.
N_OK="$(grep -c '^  \[ok\]' "$OUT/progresso.log" 2>/dev/null || true)"
N_PULADO="$(grep -c '^  \[pulado\]' "$OUT/progresso.log" 2>/dev/null || true)"
N_OK="${N_OK:-0}"; N_PULADO="${N_PULADO:-0}"

echo
echo "exportadas: $N_OK   já existentes: $N_PULADO   falhas: $N_FALHAS"
echo "manifesto:  $MANIFESTO"

if [ "$N_FALHAS" -gt 0 ]; then
  echo
  echo "$N_FALHAS tabela(s) falharam. Lista: $OUT/tabelas_com_falha.txt"
  echo "Detalhes: $FALHAS_LOG"
  echo "Rode o script de novo — ele pula o que já foi exportado."
  exit 1
fi

echo
echo "Próximo passo — baixar e verificar:"
echo "  gcloud storage rsync -r $STAGING ./bigquery/$DS"
echo
echo "Guarde o manifesto: ele tem as contagens de linha de origem, que são"
echo "a única forma de provar que o download veio completo."
