<#
  Instala/atualiza o CODIGO do datalake no projeto fixo C:\datalake\app.

  Este e o unico lugar que baixa do GitHub. As cargas do dia a dia
  (ATUALIZAR.bat, 6x/dia) NAO baixam nada -- usam o que este script deixou
  aqui. Assim o cache do GitHub nunca mais entrega codigo velho na producao.

  Faz:
    1. Baixa a versao atual da branch (com cache-buster) para C:\datalake\app.
    2. Roda a carga uma vez (-Run -KeepGoing) -- ja constroi o venv e gera a pagina.
    3. Copia ATUALIZAR.bat, servir_pagina.py, instalar_servidor.ps1 e
       diagnostico_pagina.py para C:\datalake (locais estaveis).

  O .env (credenciais do Oracle) fica em C:\datalake\.env e e devolvido ao
  projeto a cada atualizacao. Sem isso a senha do banco teria de ser digitada
  de novo toda vez, porque a pasta do projeto e apagada e rebaixada inteira.

  Uso:
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_app.ps1
    # versao exata por commit:
    powershell ... -File C:\datalake\instalar_app.ps1 -Ref c9d9b5b
#>
param(
    [string]$Ref = "claude/datalake-from-scratch-jkv3wq",
    [string]$App = "C:\datalake\app",
    [string]$LakeRoot = "C:\datalake"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

function Info($t) { Write-Host "  $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  ok: $t" -ForegroundColor Green }

# 1. baixa o codigo -------------------------------------------------------
$envEstavel = Join-Path $LakeRoot ".env"

# O .env vive dentro do projeto, e o projeto e apagado a cada atualizacao.
# Antes de apagar, guarda o que estiver la -- e a senha do Oracle.
if (-not (Test-Path $envEstavel)) {
    $envAntigo = Get-ChildItem $App -Recurse -Force -Filter ".env" -ErrorAction SilentlyContinue |
                 Select-Object -First 1
    if ($envAntigo) {
        Copy-Item $envAntigo.FullName $envEstavel -Force
        Ok "credenciais preservadas em $envEstavel"
    }
}

Info "Baixando o codigo (ref: $Ref)"
Remove-Item $App -Recurse -Force -ErrorAction SilentlyContinue
$zip = Join-Path (Split-Path $App) "app-download.zip"
# refs/heads/<branch> para branch; para commit/tag o caminho e sem refs/heads.
if ($Ref -match "/") {
    $url = "https://github.com/Fersouro/Fersouro/archive/refs/heads/$Ref.zip"
} else {
    $url = "https://github.com/Fersouro/Fersouro/archive/$Ref.zip"
}
# cache-buster: o codeload cacheia a branch por alguns minutos apos o push.
Invoke-WebRequest "$url`?cb=$(Get-Random)" -OutFile $zip -UseBasicParsing
Expand-Archive $zip $App -Force
Remove-Item $zip -Force
Ok "extraido em $App"

# checagem: o gerar_estoque.py tem o codigo novo (historico)?
$gen = (Get-ChildItem $App -Recurse -Filter gerar_estoque.py | Select-Object -First 1).FullName
if (-not $gen) { throw "Nao achei gerar_estoque.py no download." }
if (-not (Select-String -Path $gen -Pattern "historico_estoque" -Quiet)) {
    Write-Host "  AVISO: o codigo baixado parece antigo (sem historico)." -ForegroundColor Yellow
    Write-Host "         O cache do GitHub pode nao ter atualizado. Rode de novo em 1-2 min," -ForegroundColor Yellow
    Write-Host "         ou passe o commit exato:  -Ref <sha>" -ForegroundColor Yellow
}

# 2. carga + venv + pagina ------------------------------------------------
$setup = (Get-ChildItem $App -Recurse -Filter setup_windows.ps1 | Select-Object -First 1).FullName
if (-not $setup) { throw "Nao achei setup_windows.ps1 no download." }
# A raiz do projeto e a pasta com o pyproject.toml -- o mesmo criterio que o
# setup_windows.ps1 usa para achar o .env.
$projeto = Split-Path (Split-Path $setup -Parent) -Parent
if (-not (Test-Path (Join-Path $projeto "pyproject.toml"))) {
    $achado = Get-ChildItem $App -Recurse -Filter "pyproject.toml" | Select-Object -First 1
    if ($achado) { $projeto = $achado.DirectoryName }
}
if (Test-Path $envEstavel) {
    Copy-Item $envEstavel (Join-Path $projeto ".env") -Force
    Ok "credenciais restauradas no projeto (nao vai pedir a senha do Oracle)"
}

Info "Rodando a carga uma vez (constroi o venv e gera a pagina)"
& $setup -Run -KeepGoing -LakeRoot $LakeRoot

# Se a senha foi digitada agora, guarda para as proximas atualizacoes.
$envProjeto = Join-Path $projeto ".env"
if ((Test-Path $envProjeto) -and -not (Test-Path $envEstavel)) {
    Copy-Item $envProjeto $envEstavel -Force
    Ok "credenciais guardadas em $envEstavel (nao serao pedidas de novo)"
}

# 3. copia os apoios para locais estaveis ---------------------------------
Info "Copiando os apoios para $LakeRoot"
$bat = (Get-ChildItem $App -Recurse -Filter "ATUALIZAR-DATALAKE.bat" | Select-Object -First 1).FullName
if ($bat) { Copy-Item $bat (Join-Path $LakeRoot "ATUALIZAR.bat") -Force; Ok "ATUALIZAR.bat atualizado" }
$srv = (Get-ChildItem $App -Recurse -Filter "servir_pagina.py" | Select-Object -First 1).FullName
if ($srv) { Copy-Item $srv (Join-Path $LakeRoot "servir_pagina.py") -Force; Ok "servir_pagina.py atualizado" }
# o instalador do servidor da pagina: sem esta copia, o comando documentado
# (-File C:\datalake\instalar_servidor.ps1) falha dizendo que o arquivo nao existe.
$isv = (Get-ChildItem $App -Recurse -Filter "instalar_servidor.ps1" | Select-Object -First 1).FullName
if ($isv) { Copy-Item $isv (Join-Path $LakeRoot "instalar_servidor.ps1") -Force; Ok "instalar_servidor.ps1 atualizado" }
# diagnostico da pagina: responde "quem atende na porta" quando o login recusa
$dia = (Get-ChildItem $App -Recurse -Filter "diagnostico_pagina.py" | Select-Object -First 1).FullName
if ($dia) { Copy-Item $dia (Join-Path $LakeRoot "diagnostico_pagina.py") -Force; Ok "diagnostico_pagina.py atualizado" }
# o proprio instalador, para rodar de novo facil no futuro
$eu = (Get-ChildItem $App -Recurse -Filter "instalar_app.ps1" | Select-Object -First 1).FullName
if ($eu) { Copy-Item $eu (Join-Path $LakeRoot "instalar_app.ps1") -Force; Ok "instalar_app.ps1 disponivel em $LakeRoot" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Codigo instalado em $App." -ForegroundColor Green
Write-Host "  As cargas 6x/dia (ATUALIZAR.bat) usam esse projeto, sem baixar de novo." -ForegroundColor Green
Write-Host "  Pagina: $(Join-Path $LakeRoot 'export\estoque_minimo.html')" -ForegroundColor Green
Write-Host ""
Write-Host "  Proximo passo -- publicar na rede (PowerShell como Administrador):" -ForegroundColor Green
Write-Host "    powershell -NoProfile -ExecutionPolicy Bypass -File $LakeRoot\instalar_servidor.ps1 -Usuario <nome>"
Write-Host "============================================================" -ForegroundColor Green
