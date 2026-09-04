<#
  Instala a pagina de Estoque Minimo como servico na rede interna.

  Faz, de uma vez (precisa rodar como Administrador):
    1. Copia o servir_pagina.py para C:\datalake (local estavel, sobrevive ao -Update).
    2. Libera a porta no firewall do Windows.
    3. Registra uma Tarefa Agendada que sobe o servidor na INICIALIZACAO
       (conta SYSTEM: nao precisa de ninguem logado).
    4. Inicia o servico agora.

  Uso (PowerShell como Administrador):
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_servidor.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_servidor.ps1 -Porta 8090

  Para remover depois:
    Unregister-ScheduledTask -TaskName DatalakeEstoquePagina -Confirm:$false
#>
param(
    [int]$Porta = 8080,
    [string]$Pasta = "C:\datalake\export",
    [string]$Destino = "C:\datalake\servir_pagina.py"
)

$ErrorActionPreference = "Stop"
function Info($t) { Write-Host "  $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  ok: $t" -ForegroundColor Green }

# --- admin? ---------------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Precisa rodar como Administrador (firewall + tarefa como SYSTEM)." -ForegroundColor Red
    exit 1
}

# --- python do sistema ----------------------------------------------------
$py = $null
foreach ($c in @("C:\Program Files\Python312\python.exe",
                 "C:\Program Files\Python311\python.exe")) {
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) { Write-Host "Python nao encontrado no PATH." -ForegroundColor Red; exit 1 }
Ok "python em $py"

# --- 1. copia o servir_pagina.py para um lugar estavel --------------------
Info "Localizando o servir_pagina.py"
$src = $null
if (Test-Path $Destino) { $src = $Destino }
if (-not $src) {
    foreach ($raizBusca in @("C:\datalake\app", "C:\datalake", $env:USERPROFILE)) {
        if (-not (Test-Path $raizBusca)) { continue }
        $achado = Get-ChildItem $raizBusca -Recurse -Filter servir_pagina.py `
                    -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($achado) { $src = $achado.FullName; break }
    }
}
if (-not $src) {
    Write-Host "Nao achei servir_pagina.py. Rode antes o -Update para baixar o projeto." -ForegroundColor Red
    exit 1
}
if ($src -ne $Destino) {
    Copy-Item $src $Destino -Force
    Ok "copiado para $Destino"
} else {
    Ok "ja esta em $Destino"
}

# --- 2. firewall ----------------------------------------------------------
Info "Liberando a porta $Porta no firewall"
Remove-NetFirewallRule -DisplayName "Datalake Estoque $Porta" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "Datalake Estoque $Porta" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort $Porta -Profile Any | Out-Null
Ok "porta $Porta liberada (entrada TCP)"

# --- 3. tarefa agendada na inicializacao ----------------------------------
Info "Registrando a Tarefa Agendada (inicializacao, conta SYSTEM)"
$acao = New-ScheduledTaskAction -Execute $py `
    -Argument "`"$Destino`" $Porta `"$Pasta`"" -WorkingDirectory "C:\datalake"
$gatilho = New-ScheduledTaskTrigger -AtStartup
$conta = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$cfg = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Register-ScheduledTask -TaskName "DatalakeEstoquePagina" -Action $acao -Trigger $gatilho `
    -Principal $conta -Settings $cfg -Force | Out-Null
Ok "tarefa 'DatalakeEstoquePagina' registrada"

# --- 4. sobe agora --------------------------------------------------------
Info "Iniciando o servico agora"
Start-ScheduledTask -TaskName "DatalakeEstoquePagina"
Start-Sleep -Seconds 2
Ok "servico iniciado"

# --- endereco de acesso ---------------------------------------------------
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
       Sort-Object InterfaceMetric | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  PRONTO. A pagina fica no ar sozinha em toda inicializacao." -ForegroundColor Green
Write-Host ("  Acesse na rede:  http://{0}:{1}/" -f $ip, $Porta) -ForegroundColor Green
Write-Host "  (se a pagina abrir vazia, rode uma carga para gerar o estoque_minimo.html)"
Write-Host "============================================================" -ForegroundColor Green
