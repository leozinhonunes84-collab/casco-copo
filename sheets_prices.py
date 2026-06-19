from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import gspread
from google.auth.exceptions import TransportError
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def describe_google_transport_error(exc: Exception) -> str:
    message = str(exc)
    hint = (
        "Nao foi possivel conectar ao Google OAuth "
        "(https://oauth2.googleapis.com/token) para autenticar a planilha. "
        "Verifique firewall, antivirus, VPN ou proxy e libere o Python para acessar HTTPS na porta 443."
    )
    if "WinError 10013" in message or "permiss" in message.lower():
        return (
            hint
            + " No Windows, WinError 10013 normalmente indica bloqueio por permissao local de rede."
        )
    return f"{hint} Detalhe tecnico: {message}"


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "HEADLESS" and os.environ.get("PANEL_HEADLESS_OVERRIDE"):
            continue
        os.environ[key] = value


def normalize_text(value: object) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"\s+", " ", text)


def normalize_sheet_title(value: object) -> str:
    text = normalize_text(fix_mojibake(str(value or "")))
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def fix_mojibake(value: str) -> str:
    for encoding in ("cp1252", "latin1"):
        try:
            return value.encode(encoding).decode("utf-8")
        except UnicodeError:
            pass
    return value


def get_worksheet(spreadsheet, title: str):
    candidates = [title, fix_mojibake(title)]
    for candidate in dict.fromkeys(candidates):
        try:
            return spreadsheet.worksheet(candidate)
        except gspread.WorksheetNotFound:
            pass

    wanted_titles = {normalize_sheet_title(candidate) for candidate in candidates}
    for worksheet in spreadsheet.worksheets():
        if normalize_sheet_title(worksheet.title) in wanted_titles:
            return worksheet

    available = ", ".join(ws.title for ws in spreadsheet.worksheets())
    raise ValueError(f"Aba '{title}' nao encontrada. Abas disponiveis: {available}")


def money_to_cents(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        raise ValueError("valor vazio")

    text = text.replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return int(round(float(text) * 100))


@dataclass(frozen=True)
class Cadastro:
    produto: str
    locais: list[str]


@dataclass(frozen=True)
class ProdutoPrecos:
    regua: int
    p: int
    g: int
    um_litro: int

    def as_rows(self, produto: str) -> list[tuple[str, int]]:
        return [
            (f"{produto} REGUA", self.regua),
            (f"{produto} P", self.p),
            (f"{produto} G", self.g),
            (f"{produto} 1L", self.um_litro),
        ]


def open_spreadsheet():
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON nao informado")
    if credentials_json == r"C:\caminho\para\service-account.json":
        raise ValueError("GOOGLE_CREDENTIALS_JSON ainda esta com o caminho de exemplo no .env")
    if not Path(credentials_json).exists():
        raise ValueError(f"GOOGLE_CREDENTIALS_JSON nao encontrado: {credentials_json}")
    if not spreadsheet_id:
        raise ValueError("GOOGLE_SHEET_ID nao informado")
    if spreadsheet_id == "id_da_planilha":
        raise ValueError("GOOGLE_SHEET_ID ainda esta com o valor de exemplo no .env")

    creds = Credentials.from_service_account_file(credentials_json, scopes=SCOPES)
    client = gspread.authorize(creds)
    try:
        return client.open_by_key(spreadsheet_id)
    except TransportError as exc:
        raise RuntimeError(describe_google_transport_error(exc)) from exc


def read_cadastro(spreadsheet) -> Cadastro:
    aba_nome = os.environ.get("ABA_CADASTRO", "CADASTRO")
    worksheet = get_worksheet(spreadsheet, aba_nome)

    produto = normalize_text(worksheet.acell("A2").value)
    if not produto:
        raise ValueError("A celula A2 esta vazia na aba CADASTRO")

    locais = [
        normalize_text(cell.value)
        for cell in worksheet.range("B2:B8")
        if normalize_text(cell.value)
    ]
    if not locais:
        raise ValueError("Nenhum local encontrado em B2:B8 na aba CADASTRO")

    return Cadastro(produto=produto, locais=locais)


def list_sheet_products(spreadsheet) -> list[str]:
    aba_nome = os.environ.get("ABA_PRECOS", "TABELA DE PREÇO")
    worksheet = get_worksheet(spreadsheet, aba_nome)
    rows = worksheet.get_all_values()
    products = []

    for row in rows[8:]:
        if len(row) > 1:
            product = normalize_text(row[1])
            if product:
                products.append(product)

    return products


def read_price_row(spreadsheet, produto: str) -> list[str]:
    aba_nome = os.environ.get("ABA_PRECOS", "TABELA DE PREÇO")
    worksheet = get_worksheet(spreadsheet, aba_nome)
    rows = worksheet.get_all_values()

    for row in rows[8:]:
        if len(row) > 1 and normalize_text(row[1]) == produto:
            return row

    raise ValueError(f"Chope '{produto}' nao encontrado na TABELA DE PREÇO")


def _require_columns(row: list[str], indexes: Iterable[int], local: str) -> None:
    missing = [idx + 1 for idx in indexes if idx >= len(row)]
    if missing:
        raise ValueError(
            f"Linha do produto nao tem as colunas {missing} necessarias para {local}"
        )


def get_prices_for_local(row: list[str], local: str) -> ProdutoPrecos:
    if "BOTAFOGO" in normalize_text(local):
        indexes = (10, 11, 12, 13)
    else:
        indexes = (4, 5, 6, 7)

    _require_columns(row, indexes, local)
    values = [money_to_cents(row[idx]) for idx in indexes]
    return ProdutoPrecos(
        regua=values[0],
        p=values[1],
        g=values[2],
        um_litro=values[3],
    )


def upsert_report(spreadsheet, rows: list[list[object]]) -> None:
    tab_name = os.environ.get("ABA_RELATORIO", "RELATORIO API")
    try:
        worksheet = get_worksheet(spreadsheet, tab_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=100, cols=12)
    except ValueError:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=100, cols=12)

    worksheet.clear()
    if rows:
        worksheet.update("A1", rows)
