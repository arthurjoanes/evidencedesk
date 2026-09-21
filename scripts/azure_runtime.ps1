param(
    [ValidateSet('configure', 'start')][string]$Action = 'start',
    [switch]$ReadKeyFromStdin
)

$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Este helper usa DPAPI do Windows. Em outros sistemas use o secret manager da plataforma.' }
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$secretDirectory = Join-Path $env:LOCALAPPDATA 'EvidenceDesk'
$secretPath = Join-Path $secretDirectory 'azure-openai.dpapi'

if ($Action -eq 'configure') {
    if ($ReadKeyFromStdin) {
        $providedKey = [Console]::In.ReadLine()
        if ([string]::IsNullOrWhiteSpace($providedKey) -or $providedKey.Length -lt 20) {
            throw 'Credencial não recebida ou fora do formato esperado.'
        }
        $secureKey = ConvertTo-SecureString -String $providedKey.Trim() -AsPlainText -Force
        $providedKey = $null
    } else {
        $secureKey = Read-Host 'Chave Azure OpenAI (entrada oculta)' -AsSecureString
    }
    New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
    ConvertFrom-SecureString -SecureString $secureKey | Set-Content -LiteralPath $secretPath -Encoding utf8NoBOM
    $secureKey.Dispose()
    Write-Output 'Credencial protegida por DPAPI, fora do repositório e do OneDrive.'
    exit 0
}

if (-not (Test-Path -LiteralPath $secretPath -PathType Leaf)) {
    throw 'Configure a credencial com -Action configure antes de iniciar o perfil Azure.'
}
$secureKey = ConvertTo-SecureString (Get-Content -LiteralPath $secretPath -Raw).Trim()
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$previousKey = $env:AZURE_OPENAI_API_KEY
$previousProvider = $env:ED_AI_PROVIDER
$exitCode = 1
try {
    $env:AZURE_OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    $env:ED_AI_PROVIDER = 'azure_openai'
    # The CLI receives environment variables, never the key as a command argument.
    $composeArguments = @('compose', '--project-name', 'pf-evidencedesk', '-f', (Join-Path $projectRoot 'infra/compose/compose.yaml'), '-f', (Join-Path $projectRoot 'infra/compose/observability.yaml'), 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '90', 'api', 'worker')
    & docker @composeArguments
    $exitCode = $LASTEXITCODE
} finally {
    $env:AZURE_OPENAI_API_KEY = $previousKey
    $env:ED_AI_PROVIDER = $previousProvider
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    $secureKey.Dispose()
}
exit $exitCode
