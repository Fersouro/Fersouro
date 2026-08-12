<#
.SYNOPSIS
  Migração completa do datalake GCP para máquina local — versão Windows.

.DESCRIPTION
  Equivalente PowerShell dos scripts bash deste repositório, para rodar na
  máquina de destino sem depender do Cloud Shell (que vinha reciclando o
  contêiner e perdendo as credenciais no meio do trabalho).

  Executa as fases 3 e 4:
    1. Exporta as tabelas nativas do BigQuery em Parquet para um staging GCS
    2. Baixa o staging e o bucket original
    3. Verifica contagem de tabelas e integridade do bucket

  RETOMÁVEL: tabelas já exportadas são puladas. Se algo interromper, basta
  rodar de novo.

  O ÚNICO passo que escreve no GCP é o `bq extract`, que cria arquivos novos
  no staging. Nada no datalake é alterado ou apagado.

.EXAMPLE
  .\scripts\Migrar-Datalake.ps1 -Projeto tterrasul-datalake `
      -Staging gs://tterrasul-export-tmp -Destino D:\datalake
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Projeto,
  [Parameter(Mandatory = $true)][string]$Staging,
  [Parameter(Mandatory = $true)][string]$Destino,
  [string[]]$Datasets = @('lake', 'gold'),
  [string]$Bucket = '',
  [switch]$SomenteVerificar
)

$ErrorActionPreference = 'Stop'

function Escrever($msg, $cor = 'White') { Write-Host $msg -ForegroundColor $cor }
function Falhar($msg) { Escrever "ERRO: $msg" 'Red'; exit 1 }

if ($Staging -notlike 'gs://*') { Falhar "Staging precisa comecar com gs://" }

# --- Pre-requisitos --------------------------------------------------------
foreach ($cmd in @('gcloud', 'bq')) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Falhar "'$cmd' nao encontrado. Instale o Google Cloud CLI e abra um PowerShell NOVO."
  }
}

$conta = (& gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>$null)
if ([string]::IsNullOrWhiteSpace($conta)) {
  Falhar "Nenhuma conta autenticada. Rode: gcloud auth login"
}
Escrever "conta:   $conta" 'Cyan'
Escrever "projeto: $Projeto" 'Cyan'
Escrever "destino: $Destino" 'Cyan'
Escrever ""

$carimbo  = Get-Date -Format 'yyyyMMdd-HHmmss'
$pastaLog = Join-Path $Destino "_migracao-$carimbo"
New-Item -ItemType Directory -Force -Path $pastaLog | Out-Null

# --- Fase 3a: exportar cada dataset ---------------------------------------
$manifestos = @{}

foreach ($ds in $Datasets) {
  Escrever "== dataset $ds" 'Yellow'

  # O manifesto guarda row_count ANTES da exportacao. Sem esse numero de
  # origem, arquivos no disco nao provam nada na fase 4.
  # type = 1 filtra apenas BASE TABLE: views nao tem dados a exportar.
  $sql = "SELECT table_id, row_count, size_bytes FROM ``$Projeto.$ds.__TABLES__`` WHERE type = 1 ORDER BY table_id"
  $csv = & bq query --project_id=$Projeto --use_legacy_sql=false --format=csv --quiet --max_rows=100000 $sql 2>$null

  if ($LASTEXITCODE -ne 0 -or -not $csv) { Falhar "Nao foi possivel listar tabelas de $ds" }

  $tabelas = $csv | ConvertFrom-Csv
  $manifestos[$ds] = $tabelas

  $arqManifesto = Join-Path $pastaLog "manifesto-$ds.csv"
  $tabelas | Export-Csv -Path $arqManifesto -NoTypeInformation -Encoding UTF8

  $totalBytes = ($tabelas | Measure-Object -Property size_bytes -Sum).Sum
  Escrever "   $($tabelas.Count) tabelas, $totalBytes bytes"

  if ($SomenteVerificar) { continue }

  $i = 0; $ok = 0; $pulado = 0; $falhou = @()

  foreach ($t in $tabelas) {
    $i++
    $nome = $t.table_id
    Write-Progress -Activity "Exportando $ds" -Status "$i/$($tabelas.Count) - $nome" `
                   -PercentComplete (($i / $tabelas.Count) * 100)

    # Idempotencia: se ja existe algo no destino, nao refaz.
    & gcloud storage ls "$Staging/$ds/$nome/" *> $null
    if ($LASTEXITCODE -eq 0) { $pulado++; continue }

    # Parquet preserva tipos e estruturas aninhadas; CSV nao. O curinga e
    # obrigatorio: o BigQuery fatia tabelas grandes em varios arquivos.
    & bq extract --project_id=$Projeto --destination_format=PARQUET `
        "${Projeto}:${ds}.${nome}" "$Staging/$ds/$nome/*.parquet" *>> (Join-Path $pastaLog "falhas.log")

    if ($LASTEXITCODE -eq 0) { $ok++ } else { $falhou += $nome }
  }

  Write-Progress -Activity "Exportando $ds" -Completed
  Escrever "   exportadas: $ok   ja existentes: $pulado   falhas: $($falhou.Count)"

  if ($falhou.Count -gt 0) {
    $falhou | Set-Content (Join-Path $pastaLog "falhas-$ds.txt")
    Escrever "   tabelas com falha registradas em falhas-$ds.txt" 'Red'
    Escrever "   rode o script de novo: ele pula o que ja foi exportado" 'Red'
    exit 1
  }
}

# --- Fase 3b: baixar -------------------------------------------------------
if (-not $SomenteVerificar) {
  Escrever ""
  Escrever "baixando exportacoes do BigQuery..." 'Yellow'
  $destBq = Join-Path $Destino 'bigquery'
  New-Item -ItemType Directory -Force -Path $destBq | Out-Null
  & gcloud storage rsync -r $Staging $destBq
  if ($LASTEXITCODE -ne 0) { Falhar "Download das exportacoes falhou" }

  if ($Bucket) {
    Escrever ""
    Escrever "baixando o bucket original..." 'Yellow'
    $destBucket = Join-Path $Destino 'bucket'
    New-Item -ItemType Directory -Force -Path $destBucket | Out-Null
    & gcloud storage rsync -r $Bucket $destBucket
    if ($LASTEXITCODE -ne 0) { Falhar "Download do bucket falhou" }
  }
}

# --- Fase 4: verificacao ---------------------------------------------------
Escrever ""
Escrever "== verificacao" 'Yellow'
$divergencias = @()

foreach ($ds in $Datasets) {
  $esperado = $manifestos[$ds].Count
  $pastaDs  = Join-Path (Join-Path $Destino 'bigquery') $ds

  if (-not (Test-Path $pastaDs)) {
    $divergencias += "$ds : pasta ausente no destino"
    continue
  }

  $obtido = (Get-ChildItem $pastaDs -Directory -ErrorAction SilentlyContinue).Count
  Escrever "   $ds : $obtido/$esperado tabelas com arquivos"
  if ($obtido -ne $esperado) { $divergencias += "$ds : esperado $esperado, obtido $obtido" }

  # Uma tabela pode ter pasta e mesmo assim estar vazia — isso conta como falha.
  $vazias = Get-ChildItem $pastaDs -Directory -ErrorAction SilentlyContinue |
            Where-Object { -not (Get-ChildItem $_.FullName -File -ErrorAction SilentlyContinue) }
  if ($vazias) { $divergencias += "$ds : $($vazias.Count) tabela(s) sem arquivo" }
}

# O bucket usa o proprio rsync como juiz: uma segunda passada em --dry-run
# nao deve encontrar nada a fazer, ja que ele compara tamanho e checksum.
if ($Bucket) {
  $destBucket = Join-Path $Destino 'bucket'
  $pendente = & gcloud storage rsync -r --dry-run $Bucket $destBucket 2>&1 |
              Select-String -Pattern '^(Copying|Would copy)' | Measure-Object
  Escrever "   bucket : $($pendente.Count) operacoes pendentes"
  if ($pendente.Count -gt 0) { $divergencias += "bucket : rsync ainda ve diferencas" }
}

Escrever ""
if ($divergencias.Count -gt 0) {
  Escrever "VERIFICACAO FALHOU:" 'Red'
  $divergencias | ForEach-Object { Escrever "  - $_" 'Red' }
  Escrever ""
  Escrever "NAO prossiga para a desativacao da conta." 'Red'
  exit 1
}

Escrever "VERIFICADO. Log em: $pastaLog" 'Green'
Escrever ""
Escrever "Ainda pendente antes da fase 6:" 'Yellow'
Escrever "  - as 11 views do gold salvas como .sql (guarde em local PRIVADO)"
Escrever "  - descobrir e parar a automacao que alimenta o datalake"
Escrever "  - apagar o bucket de staging: gcloud storage rm -r $Staging"
