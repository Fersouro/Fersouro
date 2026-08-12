#!/bin/bash
# Inventário do que existe no GCP, antes de migrar qualquer coisa.
#
# SOMENTE LEITURA. Este script não cria, altera nem apaga nada. Todos os
# comandos usados são list/show/describe. Ele é o passo 1 da migração: sem
# saber o que existe, não há como validar que a cópia veio completa nem
# decidir com segurança o que desativar depois.
#
# Rode na SUA máquina, com suas credenciais (gcloud auth login). Não roda
# dentro do contêiner do Claude Code: o gcloud CLI não pode ser instalado lá
# (dl.google.com bloqueado) e a service account de leitura de buckets não
# enxerga BigQuery, Dataproc nem Composer.
#
# Uso:
#   ./scripts/gcp_inventory.sh                      # todos os projetos, sem tamanhos
#   ./scripts/gcp_inventory.sh --project meu-proj   # um projeto só
#   ./scripts/gcp_inventory.sh --with-sizes         # inclui tamanhos (LENTO)
set -euo pipefail

OUT_DIR="inventario-gcp-$(date +%Y%m%d-%H%M%S)"
WITH_SIZES=0
ONLY_PROJECT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --with-sizes) WITH_SIZES=1; shift ;;
    --project)    ONLY_PROJECT="${2:-}"; shift 2 ;;
    --out)        OUT_DIR="${2:-}"; shift 2 ;;
    -h|--help)    sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

if ! command -v gcloud >/dev/null 2>&1; then
  echo "erro: gcloud não encontrado. Instale o Google Cloud CLI:" >&2
  echo "  https://cloud.google.com/sdk/docs/install" >&2
  exit 2
fi

if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q .; then
  echo "erro: nenhuma conta autenticada. Rode: gcloud auth login" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
REPORT="$OUT_DIR/inventario.md"

log() { echo "  $*" >&2; }

{
  echo "# Inventário GCP"
  echo
  echo "- Gerado em: $(date -Iseconds)"
  echo "- Conta: $(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)"
  echo "- Tamanhos incluídos: $([ "$WITH_SIZES" -eq 1 ] && echo sim || echo 'não (use --with-sizes)')"
  echo
} > "$REPORT"

# Descobre os projetos a inspecionar.
if [ -n "$ONLY_PROJECT" ]; then
  PROJETOS="$ONLY_PROJECT"
else
  echo "listando projetos acessíveis..." >&2
  PROJETOS="$(gcloud projects list --format='value(projectId)')"
fi

if [ -z "$PROJETOS" ]; then
  echo "nenhum projeto acessível encontrado." >&2
  exit 1
fi

for PROJ in $PROJETOS; do
  echo "== projeto: $PROJ" >&2
  {
    echo "## Projeto \`$PROJ\`"
    echo
  } >> "$REPORT"

  # --- Cloud Storage -------------------------------------------------------
  log "buckets..."
  BUCKETS="$(gcloud storage buckets list --project="$PROJ" \
      --format='value(name)' 2>/dev/null || true)"

  {
    echo "### Cloud Storage"
    echo
    if [ -z "$BUCKETS" ]; then
      echo "_Nenhum bucket._"
    else
      echo "| Bucket | Localização | Classe | Tamanho |"
      echo "| --- | --- | --- | --- |"
    fi
  } >> "$REPORT"

  for B in $BUCKETS; do
    META="$(gcloud storage buckets describe "gs://$B" \
        --format='value(location,storageClass)' 2>/dev/null || echo -e "?\t?")"
    LOC="$(echo "$META" | cut -f1)"
    CLS="$(echo "$META" | cut -f2)"

    TAM="não medido"
    if [ "$WITH_SIZES" -eq 1 ]; then
      log "  medindo gs://$B (pode demorar)..."
      # du -s percorre todos os objetos; é o custo de ter o número exato.
      TAM="$(gcloud storage du -s "gs://$B" --readable-sizes 2>/dev/null \
             | awk '{print $1, $2}' || echo 'erro')"
    fi
    echo "| \`$B\` | $LOC | $CLS | $TAM |" >> "$REPORT"
  done
  echo >> "$REPORT"

  # --- BigQuery ------------------------------------------------------------
  log "datasets do BigQuery..."
  {
    echo "### BigQuery"
    echo
  } >> "$REPORT"

  if command -v bq >/dev/null 2>&1; then
    DATASETS="$(bq ls --project_id="$PROJ" --format=json 2>/dev/null \
                | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d=[]
for x in d: print(x["datasetReference"]["datasetId"])' 2>/dev/null || true)"

    if [ -z "$DATASETS" ]; then
      echo "_Nenhum dataset._" >> "$REPORT"
    else
      echo "| Dataset | Tabelas |" >> "$REPORT"
      echo "| --- | --- |" >> "$REPORT"
      for DS in $DATASETS; do
        N="$(bq ls -n 10000 --project_id="$PROJ" --format=json "$DS" 2>/dev/null \
             | python3 -c 'import sys,json
try: print(len(json.load(sys.stdin)))
except Exception: print("?")' 2>/dev/null || echo '?')"
        echo "| \`$DS\` | $N |" >> "$REPORT"
      done
    fi
  else
    echo "_\`bq\` não instalado — BigQuery não inspecionado._" >> "$REPORT"
  fi
  echo >> "$REPORT"

  # --- Serviços de processamento ------------------------------------------
  log "Dataproc / Composer..."
  {
    echo "### Processamento"
    echo
    echo '```'
    echo "Dataproc:"
    gcloud dataproc clusters list --project="$PROJ" --region=global 2>/dev/null \
      || echo "  (nenhum em 'global', ou API desabilitada)"
    echo
    echo "Composer:"
    gcloud composer environments list --project="$PROJ" --locations=- 2>/dev/null \
      || echo "  (nenhum, ou API desabilitada)"
    echo '```'
    echo
  } >> "$REPORT"

  # --- APIs habilitadas ----------------------------------------------------
  # Serve de rede de segurança: revela serviços que este script não cobre
  # explicitamente mas que podem guardar dados.
  log "APIs habilitadas..."
  {
    echo "### APIs habilitadas"
    echo
    echo '```'
    gcloud services list --enabled --project="$PROJ" --format='value(config.name)' 2>/dev/null \
      || echo "(não foi possível listar)"
    echo '```'
    echo
  } >> "$REPORT"
done

# --- Faturamento -----------------------------------------------------------
{
  echo "## Faturamento"
  echo
  echo '```'
  gcloud billing accounts list 2>/dev/null || echo "(sem permissão de billing, ou API desabilitada)"
  echo '```'
} >> "$REPORT"

echo >&2
echo "inventário salvo em: $REPORT" >&2
echo >&2
echo "Próximo passo: revise o relatório e confirme que nada foi esquecido." >&2
echo "A seção 'APIs habilitadas' mostra serviços que este script não cobre." >&2
