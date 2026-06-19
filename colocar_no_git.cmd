@echo off
setlocal

cd /d "%~dp0"

git --version >nul 2>nul
if errorlevel 1 (
  echo Git nao encontrado no PATH.
  pause
  exit /b 1
)

git rev-parse --verify HEAD >nul 2>nul
if errorlevel 1 (
  echo Criando commit 1/2: base do projeto
  git add .env.example .gitignore AGENTS.md README.md ^
    abrir_painel.cmd run_panel.cmd run_panel.ps1 requirements.txt ^
    ajuste_precos_dashboard.py app.py atualizar_precos_dashboard.py auditar_precos_api.py ^
    gerar_produtos_zigpay.py importar_fiscal_dashboard.py liberar_chope_dashboard.py ^
    lojas.json pagina_local.html painel_zigpay.ico preview.html sheets_prices.py zig_client.py
  if errorlevel 1 (
    echo Falha no git add da base.
    pause
    exit /b 1
  )

  git commit -m "Commit inicial da automacao ZigPay"
  if errorlevel 1 (
    echo Falha no commit inicial.
    pause
    exit /b 1
  )
) else (
  echo Commit inicial ja existe. Pulando base do projeto.
)

echo.
echo Criando commit 2/2: Item de alteracao ZigPay
git add flagar_alteracao_dashboard.py item_alteracao.html ^
  testar_item_alteracao_tijuca.py testar_item_alteracao_tijuca.cmd ^
  abrir_item_alteracao.bat painel_zigpay_azul.ico ^
  produto_unico_dashboard.py produto_unico.html abrir_produto_unico.bat ^
  painel_zigpay_cinza.ico criar_botao_produto_unico_cinza.cmd criar_botao_produto_unico_cinza.bat colocar_no_git.cmd
if errorlevel 1 (
  echo Falha no git add do Item de alteracao.
  pause
  exit /b 1
)

git diff --cached --quiet
if not errorlevel 1 (
  echo Nenhuma mudanca nova para o segundo commit.
  goto fim
)

git commit -m "Adicionar item de alteracao ZigPay"
if errorlevel 1 (
  echo Falha no commit do Item de alteracao.
  pause
  exit /b 1
)

:fim
echo.
echo Git atualizado com commits separados.
git log -1 --oneline
echo.
pause
