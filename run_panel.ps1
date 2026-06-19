$ErrorActionPreference = "Stop"

$python = "$env:LOCALAPPDATA\Python\bin\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    }
    if (-not $pythonCommand) {
        throw "Python nao encontrado. Instale o Python ou deixe o comando python/py disponivel no Windows."
    }
    $python = $pythonCommand.Source
}

Set-Location -LiteralPath $PSScriptRoot
& $python app.py
