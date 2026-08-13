<#
.SYNOPSIS
    Instala o datalake e descobre o schema Oracle, em um comando so.

.DESCRIPTION
    Faz na ordem: confere o Python, testa a rota TCP ate o banco, cria o
    ambiente virtual, instala o projeto, monta o .env e roda o discover.

    Para na primeira etapa que falhar, dizendo o que fazer -- em vez de seguir
    e quebrar tres passos adiante por um motivo que ja era conhecido.

    Tudo o que aparece na tela tambem vai para saida-datalake.txt, que e o
    arquivo para mandar de volta.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup_windows.ps1

.EXAMPLE
    # Ja sabendo o nome do schema, gera a configuracao das tabelas:
    powershell -ExecutionPolicy Bypass -File setup_windows.ps1 -Schema CCM -Write

.NOTES
    A senha e pedida na hora e nunca fica no script. Ela vai so para o .env,
    que o .gitignore ja exclui do versionamento.
#>

[CmdletBinding()]
param(
    # 'Host' sozinho colide com a variavel automatica $Host do PowerShell.
    [string]$OracleHost  = "10.15.111.254",
    [int]   $Port        = 1521,
    [string]$ServiceName = "grupoterrasul.privatesubnet.natvcn.oraclevcn.com",
    [string]$User        = "FERNANDO_DEV",
    [string]$SourceName  = "ccm",
    [string]$Schema      = "",
    [int]   $Top         = 0,    # 0 = sem limite
    [int]   $MinRows     = 0,
    [string[]]$Filter    = @(),   # aceita varios: -Filter "VEI%","FAT%"
    [switch]$Write,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$saida = Join-Path (Get-Location) "saida-datalake.txt"
try { Start-Transcript -Path $saida -Force | Out-Null } catch { }

function Etapa($numero, $texto) {
    Write-Host ""
    Write-Host "[$numero] $texto" -ForegroundColor Cyan
}
function Ok($texto)    { Write-Host "    ok: $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    !!  $texto" -ForegroundColor Yellow }
function Parar($texto) {
    Write-Host ""
    Write-Host "PAROU AQUI: $texto" -ForegroundColor Red
    Write-Host "Mande o arquivo $saida para continuarmos." -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

Write-Host "=== datalake: instalacao e descoberta do schema ===" -ForegroundColor White

# ---------------------------------------------------------------- 1. projeto
Etapa 1 "Localizando o projeto"
$raiz = $PSScriptRoot
if (-not (Test-Path (Join-Path $raiz "pyproject.toml"))) {
    $raiz = Split-Path $PSScriptRoot -Parent   # script vive em scripts/
}
if (-not (Test-Path (Join-Path $raiz "pyproject.toml"))) {
    # Antes de baixar de novo, procura uma copia ja extraida por aqui: sem isso
    # cada reexecucao rebaixa o zip inteiro sem necessidade.
    $existente = Get-ChildItem -Path (Get-Location) -Filter "pyproject.toml" -Recurse -ErrorAction SilentlyContinue |
                 Where-Object { $_.Directory.Name -eq "datalake" } |
                 Select-Object -First 1
    if ($existente) {
        $raiz = $existente.DirectoryName
        Ok "reaproveitando o projeto ja baixado"
    }
}

if (-not (Test-Path (Join-Path $raiz "pyproject.toml"))) {
    Aviso "Projeto nao encontrado ao lado do script; baixando do GitHub."
    $branch  = "claude/datalake-from-scratch-jkv3wq"
    $destino = (Get-Location).Path   # .Path: alguns cmdlets nao aceitam o PathInfo

    if (Get-Command git -ErrorAction SilentlyContinue) {
        git clone -b $branch https://github.com/Fersouro/Fersouro
    } else {
        # Sem git, o proprio PowerShell resolve: baixa o zip da branch e
        # descompacta. Invoke-WebRequest e Expand-Archive sao nativos do 5.1.
        Aviso "git nao instalado; usando download direto do zip."
        # Windows antigo negocia TLS 1.0 por padrao e o GitHub recusa.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = "SilentlyContinue"   # sem isso o download fica lento
        $zip = Join-Path $destino "datalake-projeto.zip"
        $url = "https://github.com/Fersouro/Fersouro/archive/refs/heads/$branch.zip"
        try {
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        } catch {
            Parar "Falha ao baixar $url -- $($_.Exception.Message)"
        }
        try {
            Expand-Archive -Path $zip -DestinationPath $destino -Force
        } catch {
            Parar "Falha ao descompactar o zip -- $($_.Exception.Message)"
        }
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
    }

    # O nome da pasta extraida muda conforme a branch, entao procura o projeto
    # em vez de adivinhar o caminho.
    $encontrado = Get-ChildItem -Path $destino -Filter "pyproject.toml" -Recurse -ErrorAction SilentlyContinue |
                  Where-Object { $_.DirectoryName -like "*datalake*" } |
                  Select-Object -First 1
    if (-not $encontrado) {
        Parar "Baixou mas nao encontrei a pasta datalake/ com o pyproject.toml dentro de $destino."
    }
    $raiz = $encontrado.DirectoryName
}
Set-Location $raiz
Ok "projeto em $raiz"

# ----------------------------------------------------------------- 2. python
Etapa 2 "Conferindo o Python (precisa ser 3.10 ou mais novo)"
$python = $null
foreach ($candidato in @("python", "py")) {
    $cmd = Get-Command $candidato -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
}
if (-not $python) {
    Parar "Python nao encontrado. Instale de python.org marcando 'Add Python to PATH'."
}
$versao = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>&1
if ([version]$versao -lt [version]"3.10") {
    Parar "Python $versao e antigo demais; o projeto precisa de 3.10+."
}
Ok "Python $versao em $python"

# -------------------------------------------------------------------- 3. rede
Etapa 3 "Testando a rota ate $OracleHost na porta $Port"
Write-Host "    (ate 20s; e aqui que se descobre se esta maquina alcanca o banco)"
$rota = Test-NetConnection -ComputerName $OracleHost -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $rota) {
    Parar @"
Sem rota TCP ate $OracleHost`:$Port a partir desta maquina.
Isso acontece antes de qualquer validacao de usuario e senha.
  - a VPN esta conectada?
  - esta maquina fica na mesma rede do banco?
  - o firewall libera a porta $Port?
Enquanto isso nao passar, nenhuma configuracao adianta.
"@
}
Ok "porta $Port respondendo -- esta maquina alcanca o banco"

# ------------------------------------------------------------------- 4. venv
Etapa 4 "Preparando o ambiente virtual"
$venvPython = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $python -m venv (Join-Path $raiz ".venv")
    if (-not (Test-Path $venvPython)) { Parar "Falha ao criar o .venv." }
    Ok "ambiente criado"
} else {
    Ok "ambiente ja existia"
}
# Chamar o python do venv direto dispensa o Activate.ps1 -- e o Activate e
# justamente o que costuma esbarrar em politica de execucao.
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e $raiz
if ($LASTEXITCODE -ne 0) { Parar "pip install falhou. Mande as linhas de erro acima." }
Ok "dependencias instaladas"

# -------------------------------------------------------------------- 5. .env
Etapa 5 "Configurando as credenciais (.env)"
$envPath = Join-Path $raiz ".env"
$prefixo = $SourceName.ToUpper()
$jaTem = (Test-Path $envPath) -and (Select-String -Path $envPath -Pattern "^ORACLE_${prefixo}_DSN=" -Quiet)

if ($jaTem -and -not $Force) {
    Ok ".env ja tem ORACLE_${prefixo}_*; mantido (use -Force para refazer)"
} else {
    $senhaSegura = Read-Host "    Senha de $User" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($senhaSegura)
    try {
        $senha = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    if ([string]::IsNullOrWhiteSpace($senha)) { Parar "Senha vazia." }

    $linhas = @(
        "ORACLE_${prefixo}_DSN=${OracleHost}:${Port}/${ServiceName}",
        "ORACLE_${prefixo}_USER=$User",
        "ORACLE_${prefixo}_PASSWORD=$senha"
    )
    # ASCII de proposito: com '>' ou Out-File o PowerShell 5.1 grava UTF-16, e
    # a leitura do .env sai como lixo -- o erro que aparece depois fala em
    # variavel nao definida, que nao tem nada a ver com a causa.
    if (Test-Path $envPath) {
        $atual = Get-Content $envPath | Where-Object { $_ -notmatch "^ORACLE_${prefixo}_" }
        Set-Content -Path $envPath -Value ($atual + $linhas) -Encoding ascii
    } else {
        Set-Content -Path $envPath -Value $linhas -Encoding ascii
    }
    $senha = $null
    Ok "credenciais gravadas em .env (fora do git)"
}

# --------------------------------------------------------------- 6. conexao
Etapa 6 "Conectando no banco"
& $venvPython -m datalake.cli test-connection -s $SourceName
if ($LASTEXITCODE -ne 0) {
    Parar "A rede passou mas o banco recusou. A mensagem acima diz o motivo (senha, service_name ou permissao)."
}
Ok "conectado"

# -------------------------------------------------------------- 7. discover
Etapa 7 "Descobrindo o que existe no banco"
& $venvPython -m datalake.cli discover -s $SourceName --schemas

if ($Schema) {
    Write-Host ""
    Write-Host "    Inspecionando o schema $Schema..." -ForegroundColor Cyan

    $argumentos = @("discover", "-s", $SourceName, "--schema", $Schema)
    if ($Top -gt 0)     { $argumentos += @("--top", $Top) }
    if ($MinRows -gt 0) { $argumentos += @("--min-rows", $MinRows) }
    foreach ($padrao in $Filter) { $argumentos += @("--filter", $padrao) }
    if ($Write)         { $argumentos += @("--write", "conf/sources/$SourceName.yml", "--force") }

    if (-not $Top -and -not $MinRows -and $Filter.Count -eq 0) {
        Aviso "Sem --Top/--MinRows/--Filter: em schema grande isso pode demorar e gerar saida enorme."
    }
    & $venvPython -m datalake.cli @argumentos
}

Write-Host ""
Write-Host "=== Terminou ===" -ForegroundColor Green
Write-Host "Saida completa em: $saida"
if (-not $Schema) {
    Write-Host ""
    Write-Host "Proximo passo: escolha um schema da lista acima e rode" -ForegroundColor White
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Schema NOME" -ForegroundColor White
}
try { Stop-Transcript | Out-Null } catch { }
