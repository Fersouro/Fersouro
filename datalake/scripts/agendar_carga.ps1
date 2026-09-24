<#
  Agenda a carga do datalake para rodar DE HORA EM HORA.

  Substitui as varias Tarefas Agendadas que chamavam o ATUALIZAR.bat em
  horarios fixos (7:00, 10:00, 12:00, 15:00, 17:50, 18:37) por UMA tarefa que
  se repete no intervalo escolhido. Uma tarefa so e mais facil de conferir, e o
  intervalo muda num lugar unico.

  Uso (PowerShell como Administrador):
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\agendar_carga.ps1
    ... -Inicio 06:00 -Horas 16        # janela maior
    ... -IntervaloMinutos 30           # de meia em meia hora
    ... -DiaTodo                       # 24 horas por dia
    ... -Remover                       # desfaz o agendamento

  Duas protecoes importantes:

    - MultipleInstances IgnoreNew: se uma carga passar de uma hora, a proxima
      NAO comeca por cima. Duas cargas simultaneas disputariam o mesmo lake.
    - StartWhenAvailable: se a maquina estiver desligada na hora certa, a carga
      roda assim que ela voltar, em vez de simplesmente nao acontecer.
#>
param(
    [int]$IntervaloMinutos = 60,
    [string]$Inicio = "07:00",
    [int]$Horas = 13,                       # 07:00 -> 20:00
    [switch]$DiaTodo,
    [switch]$Remover,
    [string]$Bat = "C:\datalake\ATUALIZAR.bat",
    [string]$Tarefa = "DatalakeAtualizar"
)

$ErrorActionPreference = "Stop"
function Info($t) { Write-Host "  $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  ok: $t" -ForegroundColor Green }
function Aviso($t){ Write-Host "  !!  $t" -ForegroundColor Yellow }

$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Precisa rodar como Administrador (a tarefa roda como SYSTEM)." -ForegroundColor Red
    exit 1
}

if ($Remover) {
    Unregister-ScheduledTask -TaskName $Tarefa -Confirm:$false -ErrorAction SilentlyContinue
    Ok "tarefa '$Tarefa' removida -- a carga nao roda mais sozinha"
    exit 0
}

if (-not (Test-Path $Bat)) {
    Write-Host "Nao achei $Bat. Rode antes o instalar_app.ps1." -ForegroundColor Red
    exit 1
}

# --- 1. tira do ar os agendamentos antigos da carga ------------------------
# Procura pela ACAO, nao pelo nome: as seis tarefas foram criadas a mao e nao
# seguem um padrao de nome. A tarefa da pagina (DatalakeEstoquePagina) fica de
# fora explicitamente -- ela serve o site e nao tem nada com a carga.
Info "Procurando agendamentos antigos da carga"
$antigas = @()
try {
    $antigas = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
        $_.TaskName -ne $Tarefa -and
        $_.TaskName -ne "DatalakeEstoquePagina" -and
        ($_.Actions | Where-Object {
            ("$($_.Execute) $($_.Arguments)") -match "ATUALIZAR|setup_windows\.ps1"
        })
    }
} catch {
    Aviso "nao consegui listar as tarefas existentes: $($_.Exception.Message)"
}
foreach ($t in $antigas) {
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Ok "removida: $($t.TaskName)"
}
if (-not $antigas) { Ok "nenhuma tarefa antiga encontrada" }

# --- 2. cria a tarefa que se repete ---------------------------------------
$duracao = if ($DiaTodo) { New-TimeSpan -Hours 23 -Minutes 59 } else { New-TimeSpan -Hours $Horas }
$intervalo = New-TimeSpan -Minutes $IntervaloMinutos

Info "Registrando '$Tarefa': a cada $IntervaloMinutos min, a partir das $Inicio"
$acao = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory "C:\datalake"

# O gatilho diario nao aceita repeticao direto no construtor; a forma que
# funciona no PowerShell 5.1 e emprestar o bloco Repetition de um gatilho -Once.
$gatilho = New-ScheduledTaskTrigger -Daily -At $Inicio
$gatilho.Repetition = (New-ScheduledTaskTrigger -Once -At $Inicio `
    -RepetitionInterval $intervalo -RepetitionDuration $duracao).Repetition

$conta = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$cfg = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $Tarefa -Action $acao -Trigger $gatilho `
    -Principal $conta -Settings $cfg -Force | Out-Null
Ok "tarefa registrada"

# --- 3. resumo -------------------------------------------------------------
$fim = if ($DiaTodo) { "23:59" } else { (([datetime]$Inicio).AddHours($Horas)).ToString("HH:mm") }
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  A carga passa a rodar a cada $IntervaloMinutos minutos." -ForegroundColor Green
Write-Host ("  Janela: {0} ate {1}, todos os dias." -f $Inicio, $fim) -ForegroundColor Green
Write-Host "  Carga em andamento nao e interrompida nem duplicada pela seguinte."
Write-Host ""
Write-Host "  Conferir:   schtasks /Query /TN $Tarefa /V /FO LIST"
Write-Host "  Rodar agora: schtasks /Run /TN $Tarefa"
Write-Host "  Desfazer:   powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\agendar_carga.ps1 -Remover"
Write-Host "============================================================" -ForegroundColor Green
