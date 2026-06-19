@echo off
setlocal

cd /d "%~dp0"

echo.
echo Publicando automacoes no GitHub...
echo Repositorio: leozinhonunes84-collab/casco-copo
echo Branch do GitHub Pages: principal
echo.

git --version >nul 2>nul
if errorlevel 1 (
  echo Git nao encontrado no PATH.
  echo Instale o Git for Windows e tente novamente.
  pause
  exit /b 1
)

git remote get-url origin >nul 2>nul
if errorlevel 1 (
  git remote add origin https://github.com/leozinhonunes84-collab/casco-copo.git
) else (
  git remote set-url origin https://github.com/leozinhonunes84-collab/casco-copo.git
)

git branch -M main

git add -A
if errorlevel 1 (
  echo Falha ao preparar arquivos para commit.
  pause
  exit /b 1
)

git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Atualizar backup das automacoes ZigPay"
  if errorlevel 1 (
    echo Falha ao criar commit.
    pause
    exit /b 1
  )
) else (
  echo Nenhuma mudanca nova para commitar.
)

echo.
echo Enviando para o GitHub...
echo Se pedir login, entre com a conta leozinhonunes84-collab.
echo.

git push -u origin main:principal --force-with-lease
if errorlevel 1 (
  echo.
  echo Nao foi possivel enviar para o GitHub.
  echo Verifique internet, login do GitHub e permissao no repositorio.
  pause
  exit /b 1
)

echo.
echo Pronto. A nova implantacao do GitHub Pages deve iniciar automaticamente.
echo Site: https://leozinhonunes84-collab.github.io/casco-copo/
echo.
pause
