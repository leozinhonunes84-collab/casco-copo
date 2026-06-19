# Automacao ZigPay

Este projeto separa duas tarefas:

- `app.py`: painel HTML local com abas para ajuste de preco e cadastro montavel.
- `auditar_precos_api.py`: consulta a API Zig e compara o cardapio com os precos da planilha.
- `ajuste_precos_dashboard.py`: atualiza os precos do montavel ja cadastrado no Dashboard.
- `atualizar_precos_dashboard.py`: atualiza os precos pelo Dashboard com Playwright, porque o PDF da API fornecido documenta consulta de cardapio, mas nao documenta endpoint para alterar produto/preco.
- `liberar_chope_dashboard.py`: libera chope novo na base de produtos. Por padrao roda em modo teste, sem salvar.
- `gerar_produtos_zigpay.py`: gera Excel de importacao ZigPay para produto novo ou produtos existentes.

## Configuracao

1. Instale dependencias:

```powershell
pip install -r requirements.txt
playwright install chromium
```

2. Crie um arquivo `.env` baseado no `.env.example` e preencha:

```powershell
Copy-Item .env.example .env
```

Campos principais:

- `ZIG_API_TOKEN`: chave da API Zig.
- `ZIG_REDE`: identificador da rede usado no endpoint `GET /erp/lojas` se algum local nao estiver no `lojas.json`.
- `LOJAS_JSON`: arquivo com os IDs das unidades para consulta direta na API.
- `GOOGLE_CREDENTIALS_JSON`: caminho do JSON da service account.
- `GOOGLE_SHEET_ID`: ID da planilha.
- `ZIG_ORG`, `ZIG_USER`, `ZIG_PASSWORD`: login do Dashboard, usado somente pelo Playwright.

## Painel Local

```powershell
.\run_panel.ps1
```

Abra:

```text
http://127.0.0.1:4177/preview.html
```

O painel tem duas abas:

- `Ajuste de preco`: usa Playwright para entrar no Dashboard e alterar os quatro precos do montavel ja cadastrado.
- `Cadastro montavel`: usa Playwright para cadastrar o montavel com os quatro tamanhos e precos por unidade.
- `Liberar chope novo`: usa Playwright para pesquisar o produto na base e ativar unidades. Por padrao fica em modo teste sem clicar em Salvar.
- `Gerador produtos`: gera o arquivo Excel de importacao para produto novo ou para ate 5 produtos existentes lidos do `SUBIRPRODUTOS.xlsx`.

O botao `Prever valores` le a planilha antes de rodar e mostra os valores que serao usados.

## Auditar pela API

```powershell
python auditar_precos_api.py
```

Para gravar o resultado em uma aba da planilha:

```powershell
python auditar_precos_api.py --write-sheet
```

A aba padrao e `RELATORIO API`.

## Atualizar pelo Dashboard

```powershell
python atualizar_precos_dashboard.py
```

O script le:

- `CADASTRO!A2`: nome do chope.
- `CADASTRO!B2:B8`: locais.
- `TABELA DE PREÇO`: produto na coluna B a partir da linha 9.
- Precos gerais nas colunas E:H.
- Precos de Botafogo nas colunas K:N.

Os valores sao convertidos para centavos antes de serem digitados no campo mascarado.

## IDs das Unidades

O arquivo `lojas.json` ja contem os IDs informados:

- Brewteco Gavea
- Brewteco Botafogo
- Brewteco Leblon
- Brewteco Morro da Urca
- Brewteco Rosas
- Brewteco Tijuca
- Brewteco Ferradura
- rufi.bar
- Brewteco Laranjeiras
