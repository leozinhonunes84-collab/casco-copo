@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%LOCALAPPDATA%\Python\bin\python.exe"
if exist "%PYTHON_EXE%" (
  set "PYTHON_CMD=%PYTHON_EXE%"
  goto python_ok
)

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  goto python_ok
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto python_ok
)

echo Python nao encontrado.
echo Instale o Python ou deixe o comando python/py disponivel no Windows.
echo.
pause
exit /b 1

:python_ok
set "PORT=4177"
set "HOST=0.0.0.0"
set "URL=http://127.0.0.1:4177/produto-unico.html"

echo Verificando se o painel ja esta em execucao...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4177/produto-unico.html' -TimeoutSec 1; if ($r.StatusCode -eq 200 -and $r.Content -notmatch 'Rota nao encontrada') { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto painel_pronto

powershell -NoProfile -ExecutionPolicy Bypass -Command "$conn=Get-NetTCPConnection -LocalPort 4177 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn -and $conn.OwningProcess) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1 }"

echo Iniciando servidor do painel...
start "ZigPay Produto Unico - Servidor" "%PYTHON_CMD%" -u app.py

echo Aguardando o painel responder...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='http://127.0.0.1:4177/produto-unico.html'; $end=(Get-Date).AddSeconds(20); do { try { $r=Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1; if ($r.StatusCode -eq 200 -and $r.Content -notmatch 'Rota nao encontrada') { exit 0 } } catch { Start-Sleep -Milliseconds 400 } } while ((Get-Date) -lt $end); exit 1"

if errorlevel 1 (
  echo.
  echo O servidor nao respondeu na porta %PORT%.
  echo Veja a janela "ZigPay Produto Unico - Servidor" para o erro.
  echo.
  pause
  exit /b 1
)

:painel_pronto
echo Abrindo %URL%
start "" "%URL%"

echo.
echo Pode fechar esta janela. Para encerrar o painel, feche a janela do servidor.
echo.
