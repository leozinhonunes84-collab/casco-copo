@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_CMD="%LOCALAPPDATA%\Python\bin\python.exe""
if exist "%LOCALAPPDATA%\Python\bin\python.exe" goto python_ok

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

:python_missing
echo Python nao encontrado.
echo Instale o Python ou deixe o comando python/py disponivel no Windows.
echo.
pause
exit /b 1

:python_ok
set "PORT=4177"
set "HOST=0.0.0.0"
set "URL=http://127.0.0.1:4177/preview.html"

echo Verificando se o painel ja esta em execucao...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4177/api/stores' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 goto painel_pronto

echo Iniciando servidor do painel...
start "ZigPay Local - Servidor" %PYTHON_CMD% -u app.py

echo Aguardando o painel responder...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='http://127.0.0.1:4177/api/stores'; $end=(Get-Date).AddSeconds(20); do { try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1 | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 400 } } while ((Get-Date) -lt $end); exit 1"

if errorlevel 1 (
  echo.
  echo O servidor nao respondeu na porta %PORT%.
  echo Veja a janela "ZigPay Local - Servidor" para o erro.
  echo.
  pause
  exit /b 1
)

:painel_pronto
echo Abrindo %URL%
start "" "%URL%"

echo.
echo Se preferir, abra tambem por:
echo http://%COMPUTERNAME%:4177/preview.html
echo.
echo Pode fechar esta janela. Para encerrar o painel, feche a janela do servidor.
