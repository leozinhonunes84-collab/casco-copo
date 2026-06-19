@echo off
setlocal

cd /d "%~dp0"

set "TARGET=%~dp0abrir_produto_unico.bat"
set "ICON=%~dp0painel_zigpay_cinza.ico"
set "SHORTCUT=%USERPROFILE%\Desktop\Produto unico ZigPay.lnk"

if not exist "%TARGET%" (
  echo Arquivo nao encontrado: %TARGET%
  pause
  exit /b 1
)

if not exist "%ICON%" (
  echo Icone nao encontrado: %ICON%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$shell=New-Object -ComObject WScript.Shell; $shortcut=$shell.CreateShortcut('%SHORTCUT%'); $shortcut.TargetPath='%TARGET%'; $shortcut.WorkingDirectory='%~dp0'; $shortcut.IconLocation='%ICON%'; $shortcut.Description='Abrir Produto unico ZigPay'; $shortcut.Save()"
if errorlevel 1 (
  echo Falha ao criar o botao na Area de Trabalho.
  pause
  exit /b 1
)

echo Botao criado:
echo %SHORTCUT%
echo.
echo Se o icone nao atualizar na hora, aperte F5 na Area de Trabalho.
pause
