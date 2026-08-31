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
    [string]$Find        = "",   # procura um nome em qualquer schema e tipo
    [string]$Peek        = "",   # espia as primeiras linhas de um objeto
    [string]$Sql         = "",   # consulta de leitura direto na origem
    [switch]$Run,                # carrega: bronze -> silver -> gold
    [switch]$Gold,               # so refaz gold e export, sem recarregar
    [switch]$Estoque,            # so gera a planilha de estoque minimo (sem Oracle)
    # Onde os dados ficam. Fora da pasta do projeto de proposito: o projeto e
    # descartavel (-Update apaga e rebaixa), os dados nao.
    [string]$LakeRoot    = "",
    [int]   $PeekLimit   = 10,
    [int]   $Top         = 0,    # 0 = sem limite
    [int]   $MinRows     = 0,
    [string[]]$Filter    = @(),   # aceita varios: -Filter "VEI%","FAT%"
    [switch]$Write,
    [switch]$Update,   # descarta o projeto baixado e pega a versao atual
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
if ($Update) {
    # Reaproveitar copia antiga faz o script novo rodar sobre codigo velho, e o
    # sintoma e um comando "que nao existe". -Update descarta e pega o atual.
    Get-ChildItem -Path (Get-Location) -Filter "Fersouro-*" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Aviso "removendo copia antiga: $($_.Name)"; Remove-Item $_.FullName -Recurse -Force }
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
# Modos offline (-Estoque, -Gold) leem so o que ja esta no lake em disco:
# nao tocam no Oracle, entao nao faz sentido barrar na rota ao banco.
if ($Estoque -or $Gold) {
    Etapa 3 "Rota ao banco -- pulada (modo offline, le so o lake em disco)"
    Ok "modo offline: nao preciso do Oracle"
} else {
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
}

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
if ($LakeRoot) {
    $lakeRootFinal = $LakeRoot
} else {
    # Ao lado do script, nao dentro do projeto: assim -Update nao leva os dados.
    $lakeRootFinal = Join-Path $PSScriptRoot "datalake-dados"
}
New-Item -ItemType Directory -Force -Path $lakeRootFinal | Out-Null
Ok "dados do lake em $lakeRootFinal"

# -Estoque nao usa Oracle: nao pede senha nem mexe no .env. So precisa saber
# onde o lake esta (o $lakeRootFinal acima), e o script recebe esse caminho.
if ($Estoque) {
    Ok "modo -Estoque: pulando credenciais (le so o lake em disco)"
} else {
$prefixo = $SourceName.ToUpper()
$jaTem = (Test-Path $envPath) -and (Select-String -Path $envPath -Pattern "^ORACLE_${prefixo}_DSN=" -Quiet)

if ($jaTem -and -not $Force) {
    Ok ".env ja tem ORACLE_${prefixo}_*; mantido (use -Force para refazer)"
    if (-not (Select-String -Path $envPath -Pattern "^DATALAKE_ROOT=" -Quiet)) {
        Add-Content -Path $envPath -Value "DATALAKE_ROOT=$lakeRootFinal" -Encoding ascii
        Ok "DATALAKE_ROOT acrescentado ao .env existente"
    }
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
        "ORACLE_${prefixo}_PASSWORD=$senha",
        "DATALAKE_ROOT=$lakeRootFinal"
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
}

# ----------------------------------------------------------- estoque offline
# Gera a planilha de estoque minimo a partir do lake que ja esta em disco.
# Fica aqui, antes da Etapa 6, para nao exigir a conexao ao Oracle.
if ($Estoque) {
    Write-Host ""
    Write-Host "    Gerando a pagina e a planilha de estoque minimo (sem tocar no Oracle)..." -ForegroundColor Cyan
    $catalogo = Join-Path $lakeRootFinal "lake.duckdb"
    $estoqueScript = Join-Path $raiz "scripts\gerar_estoque.py"
    if (-not (Test-Path $estoqueScript)) { $estoqueScript = Join-Path $lakeRootFinal "gerar_estoque.py" }
    if (-not (Test-Path $catalogo)) {
        Parar "Nao achei o lake em $catalogo. Rode uma carga completa antes (precisa da rota Oracle) ou informe -LakeRoot com a pasta certa."
    }
    if (-not (Test-Path $estoqueScript)) {
        Parar "Nao achei o gerar_estoque.py em $raiz\scripts nem em $lakeRootFinal."
    }
    & $venvPython $estoqueScript $catalogo
    $codigo = $LASTEXITCODE
    Write-Host ""
    if ($codigo -eq 0) {
        Write-Host "=== Pagina e planilha de estoque minimo geradas ===" -ForegroundColor Green
        Write-Host "Estao em: $(Join-Path $lakeRootFinal 'export')"
        Write-Host "Pagina: $(Join-Path $lakeRootFinal 'export\estoque_minimo.html')"
    } else {
        Write-Host "=== A geracao terminou com falha (veja acima) ===" -ForegroundColor Yellow
    }
    Write-Host "Saida completa em: $saida"
    try { Stop-Transcript | Out-Null } catch { }
    exit $codigo
}

# --------------------------------------------------------------- 6. conexao
if ($Gold) {
    Etapa 6 "Conexao ao banco -- pulada (modo -Gold, reprocessa so o lake)"
    Ok "modo offline"
} else {
    Etapa 6 "Conectando no banco"
    & $venvPython -m datalake.cli test-connection -s $SourceName
    if ($LASTEXITCODE -ne 0) {
        Parar "A rede passou mas o banco recusou. A mensagem acima diz o motivo (senha, service_name ou permissao)."
    }
    Ok "conectado"
}

# -------------------------------------------------------------- 7. discover
Etapa 7 "Descobrindo o que existe no banco"
if ($Gold) {
    # Reprocessa a partir da silver que ja esta em disco: mudar um modelo nao
    # justifica reler o ERP inteiro.
    Write-Host "    Refazendo gold e exportacao (sem tocar no Oracle)" -ForegroundColor Cyan
    & $venvPython -m datalake.cli gold
    & $venvPython -m datalake.cli export
    $codigo = $LASTEXITCODE
    Write-Host ""
    Write-Host "Arquivos em: $(Join-Path $lakeRootFinal 'export')"
    Write-Host "Saida completa em: $saida"
    try { Stop-Transcript | Out-Null } catch { }
    exit $codigo
}
if ($Run) {
    Write-Host "    Carregando: bronze -> silver -> gold" -ForegroundColor Cyan
    & $venvPython -m datalake.cli run -s $SourceName
    $codigo = $LASTEXITCODE
    Write-Host ""
    if ($codigo -eq 0) {
        Write-Host "=== Carga concluida ===" -ForegroundColor Green
        Write-Host "Os dados estao em: $(Join-Path $lakeRootFinal 'gold')"
        Write-Host "Aponte o Power BI para essa pasta (conector Parquet)."

        # Estoque minimo de pecas: gera a PAGINA (HTML) e a planilha a partir
        # do lake recem carregado. Le o disponivel real (PEC_ITEM_REVENDA.
        # qtd_contabil) -- nao inventa numero. Cai na pasta export.
        $catalogo = Join-Path $lakeRootFinal "lake.duckdb"
        $estoqueScript = Join-Path $raiz "scripts\gerar_estoque.py"
        if (-not (Test-Path $estoqueScript)) {
            $estoqueScript = Join-Path $lakeRootFinal "gerar_estoque.py"
        }
        if ((Test-Path $estoqueScript) -and (Test-Path $catalogo)) {
            Write-Host ""
            Write-Host "    Gerando a pagina e a planilha de estoque minimo..." -ForegroundColor Cyan
            & $venvPython $estoqueScript $catalogo
        }
    } else {
        Write-Host "=== Carga terminou com falhas (veja acima) ===" -ForegroundColor Yellow
    }
    Write-Host "Saida completa em: $saida"
    try { Stop-Transcript | Out-Null } catch { }
    exit $codigo
}
if ($Sql) {
    Write-Host "    Executando a consulta..." -ForegroundColor Cyan
    & $venvPython -m datalake.cli sql -s $SourceName $Sql
    Write-Host ""
    Write-Host "=== Terminou ===" -ForegroundColor Green
    Write-Host "Saida completa em: $saida"
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}
if ($Peek) {
    Write-Host "    Lendo as primeiras linhas de $Peek..." -ForegroundColor Cyan
    & $venvPython -m datalake.cli peek -s $SourceName -o $Peek -n $PeekLimit
    Write-Host ""
    Write-Host "=== Terminou ===" -ForegroundColor Green
    Write-Host "Saida completa em: $saida"
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}
if ($Find) {
    Write-Host "    Procurando '$Find' em todos os schemas..." -ForegroundColor Cyan
    & $venvPython -m datalake.cli discover -s $SourceName --find $Find
    Write-Host ""
    Write-Host "=== Terminou ===" -ForegroundColor Green
    Write-Host "Saida completa em: $saida"
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}
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
