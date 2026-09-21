[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$OperationArguments)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
& python (Join-Path $PSScriptRoot 'ops.py') @OperationArguments
exit $LASTEXITCODE
