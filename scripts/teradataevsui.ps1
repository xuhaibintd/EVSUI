# teradataevsui local service lifecycle entry point.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Action = 'status',
    [ValidateSet('all', 'web', 'worker')]
    [string]$Component = 'all',
    [ValidateRange(1, 65535)]
    [int]$Port,
    [ValidateSet('127.0.0.1', '0.0.0.0')]
    [string]$BindAddress,
    [ValidateRange(1, 86400)]
    [int]$Timeout = 30
)
$ErrorActionPreference = 'Stop'
$evsProject = Split-Path -Parent $PSScriptRoot
$evsPython = Join-Path $evsProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $evsPython -PathType Leaf)) {
    Write-Error 'Missing .venv. Create it with: python -m venv .venv; then install requirements.txt using that Python.'
    exit 1
}
$evsArguments = @((Join-Path $PSScriptRoot 'service_control.py'), $Action, '--component', $Component, '--timeout', $Timeout)
if ($PSBoundParameters.ContainsKey('Port')) { $evsArguments += @('--port', $Port) }
if ($PSBoundParameters.ContainsKey('BindAddress')) { $evsArguments += @('--bind-address', $BindAddress) }
Push-Location -LiteralPath $evsProject
try {
    & $evsPython @evsArguments
    $evsExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $evsExitCode
