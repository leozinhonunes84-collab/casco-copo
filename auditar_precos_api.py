from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sheets_prices import (
    get_prices_for_local,
    load_env_file,
    normalize_text,
    open_spreadsheet,
    read_cadastro,
    read_price_row,
    upsert_report,
)
from zig_client import DEFAULT_BASE_URL, ZigClient


HEADER = [
    "data_execucao",
    "local_planilha",
    "loja_id_api",
    "loja_nome_api",
    "produto_planilha",
    "tamanho_planilha",
    "produto_id_api",
    "produto_nome_api",
    "preco_planilha_centavos",
    "preco_api_centavos",
    "status",
]


def cents_from_api(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_store(stores: list[dict[str, Any]], local: str) -> dict[str, Any] | None:
    local_norm = normalize_text(local)
    for store in stores:
        name = normalize_text(store.get("name"))
        if name == local_norm or local_norm in name or name in local_norm:
            return store
    return None


def load_store_mapping() -> list[dict[str, Any]]:
    path = Path(os.environ.get("LOJAS_JSON", "lojas.json"))
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} deve conter uma lista de lojas")

    stores = []
    for item in data:
        if not isinstance(item, dict):
            continue
        store_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if store_id and name:
            stores.append({"id": store_id, "name": name})
    return stores


def find_product(menu: list[dict[str, Any]], expected_name: str) -> dict[str, Any] | None:
    expected_norm = normalize_text(expected_name)
    exact_match = None
    contains_match = None

    for product in menu:
        name = normalize_text(product.get("name"))
        if name == expected_norm:
            exact_match = product
            break
        if expected_norm in name or name in expected_norm:
            contains_match = contains_match or product

    return exact_match or contains_match


def build_report(write_sheet: bool) -> list[list[object]]:
    load_env_file()
    token = os.environ.get("ZIG_API_TOKEN", "").strip()
    rede = os.environ.get("ZIG_REDE", "").strip()
    base_url = os.environ.get("ZIG_BASE_URL", "").strip() or None

    spreadsheet = open_spreadsheet()
    cadastro = read_cadastro(spreadsheet)
    price_row = read_price_row(spreadsheet, cadastro.produto)

    client = ZigClient(token=token, base_url=base_url or DEFAULT_BASE_URL)
    mapped_stores = load_store_mapping()
    api_stores: list[dict[str, Any]] | None = None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report: list[list[object]] = [HEADER]

    for local in cadastro.locais:
        prices = get_prices_for_local(price_row, local)
        store = find_store(mapped_stores, local)
        if not store and rede:
            if api_stores is None:
                api_stores = client.listar_lojas(rede)
            store = find_store(api_stores, local)

        if not store:
            for size_name, expected_price in prices.as_rows(cadastro.produto):
                report.append(
                    [
                        now,
                        local,
                        "",
                        "",
                        cadastro.produto,
                        size_name,
                        "",
                        "",
                        expected_price,
                        "",
                        "LOJA_NAO_ENCONTRADA",
                    ]
                )
            continue

        store_id = str(store.get("id", ""))
        store_name = str(store.get("name", ""))
        menu = client.cardapio(store_id)

        for size_name, expected_price in prices.as_rows(cadastro.produto):
            product = find_product(menu, size_name)
            if not product:
                report.append(
                    [
                        now,
                        local,
                        store_id,
                        store_name,
                        cadastro.produto,
                        size_name,
                        "",
                        "",
                        expected_price,
                        "",
                        "PRODUTO_NAO_ENCONTRADO",
                    ]
                )
                continue

            api_price = cents_from_api(product.get("price"))
            status = "OK" if api_price == expected_price else "DIVERGENTE"
            report.append(
                [
                    now,
                    local,
                    store_id,
                    store_name,
                    cadastro.produto,
                    size_name,
                    product.get("id", ""),
                    product.get("name", ""),
                    expected_price,
                    api_price if api_price is not None else "",
                    status,
                ]
            )

    if write_sheet:
        upsert_report(spreadsheet, report)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audita no Zig API os precos de chope cadastrados na planilha."
    )
    parser.add_argument(
        "--write-sheet",
        action="store_true",
        help="Grava o resultado na aba RELATORIO API.",
    )
    args = parser.parse_args()

    report = build_report(write_sheet=args.write_sheet)
    for row in report:
        print("\t".join(str(item) for item in row))


if __name__ == "__main__":
    main()
