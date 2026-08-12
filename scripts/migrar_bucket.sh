#!/bin/bash
# Fases 3 e 4 para o bucket: copia e VERIFICA.
#
# Não escreve nada no GCP. Só lê do bucket e escreve no destino local.
#
# A verificação usa o próprio rsync como juiz: depois da cópia, roda de novo
# em modo --dry-run. O rsync compara por tamanho e checksum, então se a
# segunda passada não encontra nada a fazer, cada objeto no destino confere
# com a origem. É mais confiável do que reimplementar comparação de hash na
# mão, porque usa exatamente a mesma lógica que fez a cópia.
#
# Uso:
#   ./scripts/migrar_bucket.sh gs://tterrasul-datalake-lake ~/datalake/lake
set -euo pipefail

ORIGEM="${1:-}"
DESTINO="${2:-}"

if [ -z "$ORIGEM" ] || [ -z "$DESTINO" ]; then
  echo "uso: $0 gs://BUCKET /caminho/local" >&2
  echo "ex:  $0 gs://tterrasul-datalake-lake ~/datalake/lake" >&2
  exit 2
fi

case "$ORIGEM" in
  gs://*) ;;
  *) echo "erro: origem precisa começar com gs://" >&2; exit 2 ;;
esac

command -v gcloud >/dev/null 2>&1 || { echo "erro: 'gcloud' não encontrado." >&2; exit 2; }

if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q .; then
  echo "erro: nenhuma conta autenticada. Rode: gcloud auth login" >&2
  exit 2
fi

mkdir -p "$DESTINO"
LOG="migracao-$(date +%Y%m%d-%H%M%S).log"

echo "origem:  $ORIGEM"
echo "destino: $DESTINO"
echo "log:     $LOG"
echo

# --- Fase 3: cópia ---------------------------------------------------------
echo "[1/4] copiando..."
gcloud storage rsync -r "$ORIGEM" "$DESTINO" 2>&1 | tee -a "$LOG"

# --- Fase 4a: contagem -----------------------------------------------------
echo
echo "[2/4] contando objetos..."
N_REMOTO="$(gcloud storage ls -r "$ORIGEM/**" 2>/dev/null | grep -cv '/$' || echo 0)"
N_LOCAL="$(find "$DESTINO" -type f | wc -l | tr -d ' ')"

echo "  origem:  $N_REMOTO objetos"
echo "  destino: $N_LOCAL arquivos"

# --- Fase 4b: bytes --------------------------------------------------------
echo
echo "[3/4] somando bytes..."
B_REMOTO="$(gcloud storage du -s "$ORIGEM" 2>/dev/null | awk '{print $1}' || echo 0)"
B_LOCAL="$(find "$DESTINO" -type f -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {print s+0}')"

echo "  origem:  $B_REMOTO bytes"
echo "  destino: $B_LOCAL bytes"

# --- Fase 4c: rsync como juiz ----------------------------------------------
# Se a cópia está íntegra, uma segunda passada não tem nada a fazer.
echo
echo "[4/4] revalidando com rsync --dry-run..."
PENDENTE="$(gcloud storage rsync -r --dry-run "$ORIGEM" "$DESTINO" 2>&1 \
            | grep -cE '^(Copying|Would copy|Removing|Would remove)' || true)"

echo "  operações pendentes: $PENDENTE"

# --- Veredito --------------------------------------------------------------
echo
FALHOU=0
[ "$N_REMOTO" = "$N_LOCAL" ] || { echo "DIVERGE: contagem de objetos"; FALHOU=1; }
[ "$B_REMOTO" = "$B_LOCAL" ] || { echo "DIVERGE: total de bytes"; FALHOU=1; }
[ "$PENDENTE" = "0" ]        || { echo "DIVERGE: rsync ainda encontra diferenças"; FALHOU=1; }

{
  echo "== veredito $(date -Iseconds)"
  echo "objetos: $N_REMOTO -> $N_LOCAL"
  echo "bytes:   $B_REMOTO -> $B_LOCAL"
  echo "pendentes: $PENDENTE"
} >> "$LOG"

if [ "$FALHOU" -eq 1 ]; then
  echo
  echo "VERIFICAÇÃO FALHOU. Não prossiga para a desativação da conta."
  echo "Rode o script de novo: o rsync é retomável."
  exit 1
fi

echo "VERIFICADO: $N_LOCAL arquivos, $B_LOCAL bytes, zero diferenças."
echo
echo "Isso cobre o bucket. Ainda faltam, antes da fase 6:"
echo "  - as 11 views do dataset gold salvas como .sql"
echo "  - a resposta sobre tabelas nativas vs externas"
