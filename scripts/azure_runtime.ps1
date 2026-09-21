param(
    [ValidateSet('configure', 'start')][string]$Action = 'start',
    [string]$Endpoint,
    [string]$Deployment,
    [string]$EnvFile,
    [switch]$Observability,
    [switch]$ReadKeyFromStdin
)

$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Este helper usa DPAPI do Windows. Em outros sistemas use um arquivo de runtime protegido.' }
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$secretDirectory = Join-Path $env:LOCALAPPDATA 'EvidenceDesk'
$configurationPath = Join-Path $secretDirectory 'azure-openai.runtime.json'

function Get-ValidatedEndpoint([string]$Value) {
    # Exact public Azure inference routes; no IPs, credentials, wildcards or proxy paths.
    $hostPattern = '[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:openai\.azure\.com|services\.ai\.azure\.com)'
    $pattern = '\Ahttps://(?<resource>' + $hostPattern + ')(?::443)?/openai/v1/?\z'
    $match = [regex]::Match($Value, $pattern, [Text.RegularExpressions.RegexOptions]::IgnoreCase -bor [Text.RegularExpressions.RegexOptions]::CultureInvariant)
    if (-not $match.Success -or $Value -cmatch '[^\x20-\x7E]') {
        throw 'Informe -Endpoint https://<seu-recurso>.openai.azure.com/openai/v1/ ou o domínio services.ai.azure.com equivalente.'
    }
    $resource = $match.Groups['resource'].Value.ToLowerInvariant()
    return @{ Endpoint = "https://$resource/openai/v1/"; AllowedHost = $resource }
}

function Assert-Deployment([string]$Value) {
    if ($Value -cnotmatch '\A[A-Za-z0-9_.-]{1,100}\z') {
        throw 'Informe -Deployment com o nome do deployment existente no seu recurso Azure.'
    }
}

if ($Action -eq 'configure') {
    if ($EnvFile -or $Observability) {
        throw 'EnvFile e Observability pertencem à ação start; informe essas opções em cada inicialização.'
    }
    # Validate nonsecret metadata before asking for or replacing a credential.
    $validated = Get-ValidatedEndpoint $Endpoint
    Assert-Deployment $Deployment
    $secureKey = $null
    $temporary = $null
    try {
        if ($ReadKeyFromStdin) {
            $providedKey = [Console]::In.ReadLine()
            if ([string]::IsNullOrWhiteSpace($providedKey) -or $providedKey.Trim().Length -lt 20) {
                throw 'Credencial não recebida ou fora do formato esperado.'
            }
            $secureKey = ConvertTo-SecureString -String $providedKey.Trim() -AsPlainText -Force
            $providedKey = $null
        } else {
            $secureKey = Read-Host 'Chave Azure OpenAI (entrada oculta)' -AsSecureString
            if ($secureKey.Length -lt 20) { throw 'Credencial não recebida ou fora do formato esperado.' }
        }
        $document = @{
            SchemaVersion = 1
            Endpoint = $validated.Endpoint
            Deployment = $Deployment
            AllowedHost = $validated.AllowedHost
            ProtectedKey = ConvertFrom-SecureString -SecureString $secureKey
        } | ConvertTo-Json
        New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
        $temporary = Join-Path $secretDirectory ([guid]::NewGuid().ToString('N') + '.tmp')
        [IO.File]::WriteAllText($temporary, $document, [Text.UTF8Encoding]::new($false))
        # One atomic replacement keeps metadata and DPAPI key together.
        # Failures preserve the previous configuration and the legacy .dpapi file.
        if (Test-Path -LiteralPath $configurationPath -PathType Leaf) {
            [IO.File]::Replace($temporary, $configurationPath, [NullString]::Value)
        } else {
            [IO.File]::Move($temporary, $configurationPath)
        }
        Write-Output 'Endpoint e deployment configurados; chave protegida por DPAPI fora do repositório.'
    } finally {
        if ($secureKey) { $secureKey.Dispose() }
        if ($temporary -and (Test-Path -LiteralPath $temporary -PathType Leaf)) {
            Remove-Item -LiteralPath $temporary
        }
    }
    exit 0
}

if ($Endpoint -or $Deployment -or $ReadKeyFromStdin) {
    throw 'Endpoint, Deployment e ReadKeyFromStdin pertencem à ação configure. O start usa a configuração salva.'
}
if (-not (Test-Path -LiteralPath $configurationPath -PathType Leaf)) {
    throw 'Configuração Azure ausente ou legada: execute -Action configure -Endpoint <endpoint-v1> -Deployment <nome>. A chave .dpapi antiga foi preservada.'
}
try {
    $metadata = Get-Content -LiteralPath $configurationPath -Raw | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'Configuração Azure inválida. Execute configure com endpoint, deployment e chave; nenhum serviço foi alterado.'
}
if ($metadata.SchemaVersion -ne 1 -or -not ($metadata.ProtectedKey -is [string]) -or [string]::IsNullOrWhiteSpace($metadata.ProtectedKey)) {
    throw 'Configuração Azure incompleta. Execute configure com endpoint, deployment e chave; nenhum serviço foi alterado.'
}
$validated = Get-ValidatedEndpoint ([string]$metadata.Endpoint)
Assert-Deployment ([string]$metadata.Deployment)
if ($metadata.AllowedHost -cne $validated.AllowedHost) {
    throw 'O host autorizado não corresponde ao endpoint salvo. Execute configure novamente.'
}
$operationArguments = @((Join-Path $projectRoot 'scripts/ops.py'))
if ($EnvFile) {
    $resolvedEnv = (Resolve-Path -LiteralPath $EnvFile).Path
    if (-not (Test-Path -LiteralPath $resolvedEnv -PathType Leaf)) { throw 'EnvFile deve apontar para um arquivo de runtime.' }
    $operationArguments += @('--env-file', $resolvedEnv)
}
if ($Observability) { $operationArguments += '--observability' }
$operationArguments += 'start'

try {
    $secureKey = ConvertTo-SecureString $metadata.ProtectedKey
} catch {
    throw 'Não foi possível abrir a chave DPAPI desta conta Windows. Execute configure novamente.'
}
$keyPointer = [IntPtr]::Zero
$previousValues = @{}
foreach ($name in @('AZURE_OPENAI_API_KEY', 'ED_AI_PROVIDER', 'AZURE_OPENAI_BASE_URL', 'AZURE_OPENAI_DEPLOYMENT', 'ED_AZURE_OPENAI_ALLOWED_HOSTS')) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$exitCode = 1
try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $env:AZURE_OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    $env:ED_AI_PROVIDER = 'azure_openai'
    $env:AZURE_OPENAI_BASE_URL = $validated.Endpoint
    $env:AZURE_OPENAI_DEPLOYMENT = $metadata.Deployment
    $env:ED_AZURE_OPENAI_ALLOWED_HOSTS = $validated.AllowedHost
    # Reuse project-scoped startup and optional profiles. No secret in arguments.
    & python @operationArguments
    $exitCode = $LASTEXITCODE
} finally {
    foreach ($name in $previousValues.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousValues[$name], 'Process')
    }
    if ($keyPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer) }
    $secureKey.Dispose()
}
exit $exitCode
