<#
  Instala a pagina de Estoque Minimo (e os relatorios) como servico HTTPS na
  rede interna.

  Faz, de uma vez (precisa rodar como Administrador):
    1. Copia o servir_pagina.py para C:\datalake (local estavel, sobrevive ao -Update).
    2. Garante o pacote 'cryptography' (o certificado autoassinado depende dele).
    3. Libera as portas no firewall do Windows.
    4. Registra uma Tarefa Agendada que sobe o servidor na INICIALIZACAO
       (conta SYSTEM: nao precisa de ninguem logado).
    5. Inicia o servico agora.

  Uso (PowerShell como Administrador):
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_servidor.ps1
    ... -Escuta 192.168.78.6            # so nessa placa de rede
    ... -Porta 8443 -PortaAntiga 8080   # padrao: HTTPS na 8443, 8080 redireciona
    ... -Usuario fernando               # cadastra quem pode entrar (pede a senha)
    ... -Http                           # sem TLS, como era antes
    ... -SemLogin                        # servir sem senha (nao recomendado)

  O acesso pede usuario e senha (a pasta export tem margem e faturamento). O
  primeiro usuario e cadastrado aqui; os demais, com:
    & "C:\Program Files\Python312\python.exe" "C:\datalake\servir_pagina.py" --criar-usuario <nome>

  O certificado e autoassinado: o navegador avisa na primeira visita. Para
  tirar o aviso, instale C:\datalake\cert\servidor.pem como "Autoridade de
  Certificacao Raiz Confiavel" nas maquinas (da para distribuir por GPO).

  Para remover depois:
    Unregister-ScheduledTask -TaskName DatalakeEstoquePagina -Confirm:$false
#>
param(
    [int]$Porta = 8443,
    [int]$PortaAntiga = 8080,
    [string]$Escuta = "0.0.0.0",
    [string]$Usuario = "",
    [switch]$SemLogin,
    [switch]$Http,
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

# --- 2. pacote do certificado --------------------------------------------
if (-not $Http) {
    Info "Garantindo o pacote 'cryptography' (certificado autoassinado)"
    & $py -m pip install --quiet --disable-pip-version-check cryptography 2>&1 | Out-Null
    & $py -c "import cryptography" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Nao consegui instalar o 'cryptography' para $py." -ForegroundColor Red
        Write-Host "Instale na mao ('$py -m pip install cryptography') ou rode com -Http." -ForegroundColor Red
        exit 1
    }
    Ok "cryptography disponivel"
}

# --- 2b. usuarios do portal ----------------------------------------------
$arqUsuarios = Join-Path (Split-Path $Pasta -Parent) "usuarios.json"
if ($SemLogin) {
    Write-Host "  ATENCAO: -SemLogin -- qualquer maquina da rede baixa as planilhas." -ForegroundColor Yellow
} else {
    if ($Usuario) {
        Info "Cadastrando o usuario '$Usuario'"
        & $py $Destino --criar-usuario $Usuario --pasta $Pasta
        if ($LASTEXITCODE -ne 0) { Write-Host "Cadastro cancelado." -ForegroundColor Red; exit 1 }
    } elseif (-not (Test-Path $arqUsuarios)) {
        Info "Nenhum usuario cadastrado ainda -- vamos criar o primeiro"
        $novo = Read-Host "    Nome de usuario (ex.: fernando)"
        if ([string]::IsNullOrWhiteSpace($novo)) {
            Write-Host "Sem usuario o servidor nao sobe. Rode de novo com -Usuario <nome>," -ForegroundColor Red
            Write-Host "ou com -SemLogin para servir sem senha." -ForegroundColor Red
            exit 1
        }
        & $py $Destino --criar-usuario $novo --pasta $Pasta
        if ($LASTEXITCODE -ne 0) { Write-Host "Cadastro cancelado." -ForegroundColor Red; exit 1 }
    }
    Ok "usuarios em $arqUsuarios"
}

# --- 3. firewall ----------------------------------------------------------
$portas = @($Porta)
if (-not $Http -and $PortaAntiga -gt 0 -and $PortaAntiga -ne $Porta) { $portas += $PortaAntiga }
foreach ($pt in $portas) {
    Info "Liberando a porta $pt no firewall"
    Remove-NetFirewallRule -DisplayName "Datalake Estoque $pt" -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "Datalake Estoque $pt" -Direction Inbound `
        -Action Allow -Protocol TCP -LocalPort $pt -Profile Any | Out-Null
    Ok "porta $pt liberada (entrada TCP)"
}

# --- 4. tarefa agendada na inicializacao ----------------------------------
Info "Registrando a Tarefa Agendada (inicializacao, conta SYSTEM)"
$argumentos = "`"$Destino`" --porta $Porta --pasta `"$Pasta`" --host $Escuta"
if ($SemLogin) { $argumentos += " --sem-login" }
if ($Http) {
    $argumentos += " --http"
} elseif ($PortaAntiga -gt 0 -and $PortaAntiga -ne $Porta) {
    $argumentos += " --redirecionar-de $PortaAntiga"
} else {
    $argumentos += " --sem-redirecionar"
}
$acao = New-ScheduledTaskAction -Execute $py `
    -Argument $argumentos -WorkingDirectory "C:\datalake"
$gatilho = New-ScheduledTaskTrigger -AtStartup
$conta = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$cfg = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Register-ScheduledTask -TaskName "DatalakeEstoquePagina" -Action $acao -Trigger $gatilho `
    -Principal $conta -Settings $cfg -Force | Out-Null
Ok "tarefa 'DatalakeEstoquePagina' registrada"

# --- 5. sobe agora --------------------------------------------------------
Info "Iniciando o servico agora"
Start-ScheduledTask -TaskName "DatalakeEstoquePagina"
Start-Sleep -Seconds 2
Ok "servico iniciado"

# --- endereco de acesso ---------------------------------------------------
$ip = $Escuta
if ($ip -eq "0.0.0.0") {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
           Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
           Sort-Object InterfaceMetric | Select-Object -First 1).IPAddress
}
$esquema = if ($Http) { "http" } else { "https" }
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  PRONTO. A pagina fica no ar sozinha em toda inicializacao." -ForegroundColor Green
Write-Host ("  Acesse na rede:  {0}://{1}:{2}/" -f $esquema, $ip, $Porta) -ForegroundColor Green
Write-Host ("  Relatorios:      {0}://{1}:{2}/relatorios/" -f $esquema, $ip, $Porta) -ForegroundColor Green
if (-not $Http) {
    if ($PortaAntiga -gt 0 -and $PortaAntiga -ne $Porta) {
        Write-Host ("  A porta {0} redireciona para o HTTPS (links antigos continuam valendo)." -f $PortaAntiga)
    }
    Write-Host "  Certificado autoassinado: o navegador avisa na primeira visita."
    Write-Host "  Para tirar o aviso, instale C:\datalake\cert\servidor.pem como raiz confiavel."
}
if (-not $SemLogin) {
    Write-Host "  A pagina pede usuario e senha. Para cadastrar mais gente:"
    # Com o '&' e as aspas: o caminho do Python tem espaco, e sem o '&' o
    # PowerShell trata a linha como texto e devolve 'Token inesperado'.
    Write-Host ("    & `"{0}`" `"{1}`" --criar-usuario <nome>" -f $py, $Destino)
}
Write-Host "  (se a pagina abrir vazia, rode uma carga para gerar o estoque_minimo.html)"
Write-Host "============================================================" -ForegroundColor Green
