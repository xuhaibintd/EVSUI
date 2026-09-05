# Compatibility entry point for existing launch commands.
& (Join-Path $PSScriptRoot 'teradataevsui.ps1') @args
exit $LASTEXITCODE
