param([ValidateRange(1024, 65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m uvicorn app:app --host 127.0.0.1 --port $Port --reload
