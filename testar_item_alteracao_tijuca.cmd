@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_CMD=%LOCALAPPDATA%\Python\bin\python.exe"
if not exist "%PYTHON_CMD%" (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py"
  ) else (
    where python >nul 2>nul
    if not errorlevel 1 (
      set "PYTHON_CMD=python"
    ) else (
      echo Python nao encontrado.
      pause
      exit /b 1
    )
  )
)

set "HEADLESS=true"
echo Testando Item de alteracao ZigPay
echo Unidade: BREWTECO TIJUCA
echo SKU: 74737372828673
echo.

"%PYTHON_CMD%" -u testar_item_alteracao_tijuca.py > teste_item_alteracao_tijuca.log 2> teste_item_alteracao_tijuca.err.log
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo ==== LOG ====
type teste_item_alteracao_tijuca.log

echo.
echo ==== ERROS ====
type teste_item_alteracao_tijuca.err.log

echo.
if "%EXIT_CODE%"=="0" (
  echo Teste finalizado. Veja o relatorio em EXPORTACOES_ZIGPAY.
) else (
  echo Teste terminou com erro. Veja teste_item_alteracao_tijuca.err.log.
)
echo.
pause
exit /b %EXIT_CODE%
