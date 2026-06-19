from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ajuste_precos_dashboard import run_price_adjust_dashboard
from auditar_precos_api import cents_from_api, find_product, load_store_mapping
from atualizar_precos_dashboard import run_dashboard_update
from gerar_produtos_zigpay import (
    GRUPOS_FISCAIS,
    LOCAIS as GERADOR_LOCAIS,
    buscar_produtos,
    gerar_produto_existente,
    gerar_produto_novo,
    gerar_replicacao_fiscal,
)
from flagar_alteracao_dashboard import run_flagar_alteracao_produtos_dashboard
from importar_fiscal_dashboard import run_importar_fiscal_dashboard, run_importar_produtos_dashboard
from liberar_chope_dashboard import run_liberar_chope_dashboard
from produto_unico_dashboard import run_produto_unico_dashboard
from sheets_prices import (
    get_prices_for_local,
    load_env_file,
    normalize_text,
    open_spreadsheet,
    read_price_row,
)
from zig_client import DEFAULT_BASE_URL, ZigClient


ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "4177"))
HOST = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"


@dataclass
class Job:
    id: str
    action: str
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    def log(self, message: str) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        self.logs.append(f"{datetime.now().strftime('%H:%M:%S')} - {message}")


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()


class JobLogWriter:
    def __init__(self, job: Job) -> None:
        self.job = job
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.job.log(line.strip())
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self.job.log(self._buffer.strip())
        self._buffer = ""


def selected_stores(unit_ids: list[str]) -> list[dict[str, Any]]:
    stores = load_store_mapping()
    if not unit_ids:
        return stores
    wanted = {str(unit_id).strip() for unit_id in unit_ids}
    return [store for store in stores if str(store.get("id", "")).strip() in wanted]


def prices_for(product: str, stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spreadsheet = open_spreadsheet()
    product_norm = normalize_text(product)
    if not product_norm:
        raise ValueError("Informe o nome do chope")

    row = read_price_row(spreadsheet, product_norm)
    output = []
    for store in stores:
        local = str(store["name"])
        prices = get_prices_for_local(row, local)
        output.append(
            {
                "store_id": store["id"],
                "store_name": local,
                "product": product_norm,
                "prices": [
                    {"name": name, "price": value}
                    for name, value in prices.as_rows(product_norm)
                ],
            }
        )
    return output


def zig_client_from_env() -> ZigClient:
    token = os.environ.get("ZIG_API_TOKEN", "").strip()
    base_url = os.environ.get("ZIG_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    return ZigClient(token=token, base_url=base_url)


def cents_from_manual(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Informe todos os precos manuais")
    text = text.replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = float(text)
    except ValueError as exc:
        raise ValueError(f"Preco manual invalido: {value}") from exc
    if amount < 0:
        raise ValueError("Preco manual nao pode ser negativo")
    return int(round(amount * 100))


def manual_prices_from_payload(payload: dict[str, Any]) -> dict[str, int] | None:
    if not bool(payload.get("manual_price_enabled", False)):
        return None
    prices = payload.get("manual_prices", {})
    if not isinstance(prices, dict):
        raise ValueError("Precos manuais invalidos")
    return {
        "REGUA": cents_from_manual(prices.get("REGUA")),
        "P": cents_from_manual(prices.get("P")),
        "G": cents_from_manual(prices.get("G")),
        "1L": cents_from_manual(prices.get("1L")),
    }


def precise_skus_from_payload(payload: dict[str, Any]) -> dict[str, str] | None:
    if not bool(payload.get("precise_sku_enabled", False)):
        return None
    raw = payload.get("precise_skus", {})
    if not isinstance(raw, dict):
        raise ValueError("SKUs da busca precisa invalidos")
    skus = {
        key: str(raw.get(key, "")).strip().removeprefix("#")
        for key in ["MAIN", "REGUA", "P", "G", "1L"]
    }
    if not skus["MAIN"]:
        raise ValueError("Informe pelo menos o SKU Principal na busca precisa")
    return skus


def run_price_adjust_api(job: Job, payload: dict[str, Any]) -> None:
    product = str(payload.get("product", "")).strip()
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    stores = selected_stores(unit_ids)
    if not stores:
        raise ValueError("Selecione pelo menos uma unidade")

    client = zig_client_from_env()
    plan = prices_for(product, stores)
    rows = []

    for item in plan:
        job.log(f"Consultando cardapio API: {item['store_name']}")
        menu = client.cardapio(item["store_id"])
        for expected in item["prices"]:
            product_api = find_product(menu, expected["name"])
            current_price = cents_from_api(product_api.get("price")) if product_api else None
            if product_api and current_price == expected["price"]:
                status = "OK"
            elif product_api:
                status = "PENDENTE_ENDPOINT_API"
            else:
                status = "PRODUTO_NAO_ENCONTRADO"
            rows.append(
                {
                    "store": item["store_name"],
                    "store_id": item["store_id"],
                    "name": expected["name"],
                    "expected_price": expected["price"],
                    "api_product_id": product_api.get("id", "") if product_api else "",
                    "api_product_name": product_api.get("name", "") if product_api else "",
                    "api_price": current_price,
                    "status": status,
                }
            )

    job.result = {
        "message": "Consulta concluida. O PDF da API nao documenta endpoint para gravar ajuste de preco.",
        "rows": rows,
    }


def run_mountable_api(job: Job, payload: dict[str, Any]) -> None:
    product = str(payload.get("product", "")).strip()
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    stores = selected_stores(unit_ids)
    if not stores:
        raise ValueError("Selecione pelo menos uma unidade")

    plan = prices_for(product, stores)
    rows = []
    for item in plan:
        job.log(f"Preparando cadastro montavel: {item['store_name']}")
        for expected in item["prices"]:
            rows.append(
                {
                    "store": item["store_name"],
                    "store_id": item["store_id"],
                    "name": expected["name"],
                    "expected_price": expected["price"],
                    "status": "PENDENTE_ENDPOINT_API",
                }
            )

    job.result = {
        "message": "Plano montado. O PDF da API nao documenta endpoint para cadastrar montavel.",
        "rows": rows,
    }


def run_price_adjust_dashboard_job(job: Job, payload: dict[str, Any]) -> None:
    product = str(payload.get("product", "")).strip()
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    stores = selected_stores(unit_ids)
    if not stores:
        raise ValueError("Selecione pelo menos uma unidade")

    store_names = [str(store["name"]).upper() for store in stores]
    manual_prices = manual_prices_from_payload(payload)
    precise_skus = precise_skus_from_payload(payload)
    if manual_prices:
        job.log("Usando ajuste manual de precos.")
    if precise_skus:
        job.log(f"Busca precisa por SKU ativada: principal #{precise_skus['MAIN']}")
    errors = run_price_adjust_dashboard(product, store_names, manual_prices, job.log, precise_skus)
    rows = [
        {
            "store": store["name"],
            "name": product.upper(),
            "expected_price": "",
            "api_price": "",
            "status": "ERRO" if any(err["store"] == store["name"].upper() for err in errors) else "OK",
        }
        for store in stores
    ]
    job.result = {
        "message": "Ajuste de preco finalizado.",
        "rows": rows,
        "errors": errors,
    }


def run_mountable_dashboard_job(job: Job, payload: dict[str, Any]) -> None:
    product = str(payload.get("product", "")).strip()
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    stores = selected_stores(unit_ids)
    if not stores:
        raise ValueError("Selecione pelo menos uma unidade")

    store_names = [str(store["name"]).upper() for store in stores]
    manual_prices = manual_prices_from_payload(payload)
    precise_skus = precise_skus_from_payload(payload)
    if manual_prices:
        job.log("Usando ajuste manual de precos no montavel.")
    if precise_skus:
        job.log(f"Busca precisa por SKU ativada: principal #{precise_skus['MAIN']}")
    writer = JobLogWriter(job)
    with redirect_stdout(writer):
        errors = run_dashboard_update(product, store_names, manual_prices, precise_skus)
    writer.flush()
    rows = [
        {
            "store": store["name"],
            "name": product.upper(),
            "expected_price": "",
            "api_price": "",
            "status": "ERRO" if any(err[0] == store["name"].upper() for err in errors) else "OK",
        }
        for store in stores
    ]
    job.result = {
        "message": "Cadastro montavel finalizado.",
        "rows": rows,
        "errors": errors,
    }


def run_release_beer_job(job: Job, payload: dict[str, Any]) -> None:
    product = str(payload.get("product", "")).strip()
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    if not unit_ids:
        raise ValueError("Selecione pelo menos uma unidade para liberar")
    dry_run = bool(payload.get("dry_run", True))
    stores = selected_stores(unit_ids)
    store_names = [str(store["name"]).upper() for store in stores]

    job.log("Fluxo atualizado: sincronizando Locais exatamente, sem botoes legacy.")
    result = run_liberar_chope_dashboard(
        product,
        store_names,
        dry_run=dry_run,
        log=job.log,
    )
    status = "TESTE_OK" if dry_run else "OK"
    job.result = {
        "message": "Teste de liberacao finalizado." if dry_run else "Liberacao finalizada.",
        "rows": [
            {
                "store": store["name"],
                "name": product.upper(),
                "expected_price": "",
                "api_price": "",
                "status": status,
            }
            for store in stores
        ],
        "details": result,
    }


def run_generate_product_job(job: Job, payload: dict[str, Any]) -> None:
    mode = str(payload.get("generator_mode", "new"))
    local = str(payload.get("generator_local", "")).strip() or GERADOR_LOCAIS[0]
    fiscal_group = str(payload.get("fiscal_group", "")).strip() or GRUPOS_FISCAIS[0]
    replicate_fiscal = bool(payload.get("replicate_fiscal", True))

    if mode == "new":
        result = gerar_produto_novo(
            str(payload.get("product", "")),
            str(payload.get("sku_start", "")),
            int(payload.get("sku_skip", 0) or 0),
            local,
            fiscal_group,
            replicate_fiscal,
        )
    elif mode == "existing":
        selected = payload.get("selected_products", [])
        if not isinstance(selected, list):
            raise ValueError("selected_products deve ser uma lista")
        result = gerar_produto_existente(selected, local, fiscal_group, replicate_fiscal)
    else:
        raise ValueError(f"Modo de gerador desconhecido: {mode}")

    job.log(f"Excel gerado: {result['filename']}")
    job.log(f"Caminho: {result['path']}")
    job.log("Iniciando importacao em massa no Dashboard ZigPay...")
    errors = run_importar_produtos_dashboard([result], job.log)
    job.result = {
        "message": (
            "Produtos importados no Dashboard ZigPay."
            if not errors
            else f"Gerador concluido com {len(errors)} erro(s) na importacao."
        ),
        "rows": [
            {
                "store": local,
                "name": result["filename"],
                "expected_price": "",
                "api_price": "",
                "status": "ERRO" if errors else "OK",
            }
        ],
        "details": result,
        "errors": errors,
    }


def run_replicate_fiscal_job(job: Job, payload: dict[str, Any]) -> None:
    product = str(payload.get("product", "")).strip()
    fiscal_source = str(payload.get("generator_local", "")).strip() or GERADOR_LOCAIS[0]
    fiscal_group = str(payload.get("fiscal_group", "")).strip() or GRUPOS_FISCAIS[0]
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    stores = selected_stores(unit_ids)
    if not stores:
        raise ValueError("Marque pelo menos uma unidade para receber o fiscal")

    target_names = [str(store["name"]).upper() for store in stores]
    precise_skus = precise_skus_from_payload(payload)
    result = gerar_replicacao_fiscal(product, fiscal_source, target_names, fiscal_group)
    if precise_skus:
        missing = [key for key in ["MAIN", "REGUA", "P", "G", "1L"] if not precise_skus[key]]
        if missing:
            raise ValueError(
                "Para replicar fiscal com busca precisa, informe todos os SKUs: "
                + ", ".join(missing)
            )
        job.log("Busca precisa por SKU ativada para os 5 produtos fiscais.")
        for file_info in result["files"]:
            file_info["precise_skus"] = precise_skus
    for file_info in result["files"]:
        job.log(f"Excel fiscal gerado para {file_info['target']}: {file_info['filename']}")
        job.log(f"Caminho: {file_info['path']}")
    job.log("Iniciando importacao no Dashboard ZigPay...")
    errors = run_importar_fiscal_dashboard(result["files"], job.log)
    job.result = {
        "message": (
            "Replicacao fiscal importada no Dashboard ZigPay."
            if not errors
            else f"Replicacao fiscal concluida com {len(errors)} erro(s)."
        ),
        "rows": [
            {
                "store": target,
                "name": next(
                    item["filename"]
                    for item in result["files"]
                    if item["target"] == target
                ),
                "expected_price": "",
                "api_price": "",
                "status": "ERRO" if any(error["store"] == target for error in errors) else "OK",
            }
            for target in target_names
        ],
        "details": result,
        "errors": errors,
    }


def run_flag_alteration_job(job: Job, payload: dict[str, Any]) -> None:
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    if not unit_ids:
        raise ValueError("Selecione pelo menos uma unidade")
    stores = selected_stores(unit_ids)
    if not stores:
        raise ValueError("Selecione pelo menos uma unidade")

    store_names = [str(store["name"]).upper() for store in stores]
    result = run_flagar_alteracao_produtos_dashboard(
        store_names,
        payload.get("alteration_codes", ""),
        job.log,
        payload.get("alteration_file") if isinstance(payload.get("alteration_file"), dict) else None,
    )

    rows = [
        {
            "store": row.get("unidade", ""),
            "name": f"SKU #{row.get('sku', '')}".strip(),
            "expected_price": "",
            "api_price": "",
            "status": row.get("status", ""),
        }
        for row in result["rows"]
    ]
    job.result = {
        "message": "Verificacao de item de alteracao finalizada.",
        "rows": rows,
        "details": result,
        "download_url": f"/api/exportacoes/{result['report_filename']}" if result.get("report_filename") else "",
    }


def run_unique_product_job(job: Job, payload: dict[str, Any]) -> None:
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    if not unit_ids:
        raise ValueError("Selecione pelo menos uma unidade")
    stores = selected_stores(unit_ids)
    if not stores:
        raise ValueError("Selecione pelo menos uma unidade")

    store_names = [str(store["name"]).upper() for store in stores]
    result = run_produto_unico_dashboard(
        store_names,
        payload.get("unique_rows", ""),
        job.log,
        payload.get("unique_file") if isinstance(payload.get("unique_file"), dict) else None,
        str(payload.get("fiscal_source", "")),
        str(payload.get("fiscal_group", "")) or GRUPOS_FISCAIS[0],
        payload.get("unique_steps"),
    )
    rows = [
        {
            "store": row.get("unidade", ""),
            "name": f"SKU #{row.get('sku', '')}".strip(),
            "expected_price": row.get("preco_planilha_centavos", ""),
            "api_price": row.get("preco_atual_centavos", ""),
            "source_price": row.get("preco_origem_centavos", ""),
            "fiscal_status": row.get("fiscal_status", ""),
            "status": row.get("status", ""),
        }
        for row in result["rows"]
    ]
    job.result = {
        "message": "Atualizacao de produto unico finalizada.",
        "rows": rows,
        "details": result,
        "download_url": f"/api/exportacoes/{result['report_filename']}" if result.get("report_filename") else "",
    }


SEQUENCE_STEP_LABELS = {
    "generate_product": "Cadastrar produto",
    "release_beer": "Liberar chope",
    "replicate_fiscal": "Ajustar fiscal",
    "mountable": "Cadastrar montavel",
}


def normalize_sequence_steps(raw_steps: object) -> list[str]:
    if not isinstance(raw_steps, list):
        return ["generate_product", "release_beer", "replicate_fiscal", "mountable"]

    steps: list[str] = []
    for item in raw_steps:
        step = str(item).strip()
        if step in SEQUENCE_STEP_LABELS and step not in steps:
            steps.append(step)
    if not steps:
        raise ValueError("Selecione pelo menos uma etapa do fluxo")
    return steps


def append_step_rows(
    rows: list[dict[str, Any]],
    step: str,
    result: dict[str, Any] | None,
    status: str,
) -> None:
    step_label = SEQUENCE_STEP_LABELS.get(step, step)
    source_rows = (result or {}).get("rows") or []
    if not source_rows:
        rows.append(
            {
                "store": step_label,
                "name": "",
                "expected_price": "",
                "api_price": "",
                "status": status,
            }
        )
        return

    for row in source_rows:
        rows.append(
            {
                "store": row.get("store", step_label),
                "name": f"{step_label}: {row.get('name', '')}".strip(),
                "expected_price": row.get("expected_price", ""),
                "api_price": row.get("api_price", ""),
                "status": row.get("status") or status,
            }
        )


def result_has_errors(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        return True
    rows = result.get("rows")
    if isinstance(rows, list):
        return any(str(row.get("status", "")).upper() == "ERRO" for row in rows if isinstance(row, dict))
    return False


def run_product_sequence_job(job: Job, payload: dict[str, Any]) -> None:
    product = str(payload.get("product", "")).strip()
    if not product:
        raise ValueError("Informe o nome do chope")
    unit_ids = [str(item) for item in payload.get("unit_ids", [])]
    if not unit_ids:
        raise ValueError("Selecione pelo menos uma unidade")

    steps = normalize_sequence_steps(payload.get("sequence_steps"))
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    job.log("Fluxo completo iniciado.")
    job.log("Sequencia: " + " > ".join(SEQUENCE_STEP_LABELS[step] for step in steps))

    for index, step in enumerate(steps, start=1):
        label = SEQUENCE_STEP_LABELS[step]
        job.log(f"[{index}/{len(steps)}] Etapa: {label}")
        job.result = None

        if step == "generate_product":
            step_payload = {**payload, "replicate_fiscal": True}
            run_generate_product_job(job, step_payload)
        elif step == "release_beer":
            run_release_beer_job(job, payload)
        elif step == "replicate_fiscal":
            run_replicate_fiscal_job(job, payload)
        elif step == "mountable":
            run_mountable_dashboard_job(job, payload)
        else:
            raise ValueError(f"Etapa desconhecida: {step}")

        step_result = job.result or {}
        failed = result_has_errors(step_result)
        details.append({"step": step, "label": label, "status": "ERRO" if failed else "OK", "result": step_result})
        append_step_rows(rows, step, step_result, "ERRO" if failed else "OK")
        if failed:
            job.result = {
                "message": f"Fluxo interrompido na etapa: {label}.",
                "rows": rows,
                "details": details,
                "errors": step_result.get("errors", []),
            }
            raise RuntimeError(f"Fluxo interrompido na etapa: {label}")

    job.result = {
        "message": "Fluxo completo finalizado.",
        "rows": rows,
        "details": details,
    }


def run_job(job_id: str, payload: dict[str, Any]) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.status = "running"
        job.log("Tarefa iniciada")

    original_headless = os.environ.get("HEADLESS")
    original_headless_override = os.environ.get("PANEL_HEADLESS_OVERRIDE")
    try:
        if "headless_mode" in payload:
            os.environ["PANEL_HEADLESS_OVERRIDE"] = "1"
            os.environ["HEADLESS"] = "true" if bool(payload.get("headless_mode")) else "false"
            if bool(payload.get("headless_mode")):
                job.log("Modo invisivel ativado.")

        action = job.action
        if action == "price_adjust_dashboard":
            run_price_adjust_dashboard_job(job, payload)
        elif action == "mountable_dashboard":
            run_mountable_dashboard_job(job, payload)
        elif action == "release_beer_dashboard":
            run_release_beer_job(job, payload)
        elif action == "generate_product_excel":
            run_generate_product_job(job, payload)
        elif action == "replicate_fiscal_excel":
            run_replicate_fiscal_job(job, payload)
        elif action == "flag_alteration_items":
            run_flag_alteration_job(job, payload)
        elif action == "unique_product_prices":
            run_unique_product_job(job, payload)
        elif action == "product_full_sequence":
            run_product_sequence_job(job, payload)
        elif action == "price_adjust_api":
            run_price_adjust_api(job, payload)
        elif action == "mountable_api":
            run_mountable_api(job, payload)
        else:
            raise ValueError(f"Acao desconhecida: {action}")
        job.status = "done"
        job.log("Tarefa finalizada")
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        job.log("Erro: " + str(exc))
        current_result = job.result if isinstance(job.result, dict) else {}
        current_result["traceback"] = traceback.format_exc()
        job.result = current_result
    finally:
        if original_headless is None:
            os.environ.pop("HEADLESS", None)
        else:
            os.environ["HEADLESS"] = original_headless
        if original_headless_override is None:
            os.environ.pop("PANEL_HEADLESS_OVERRIDE", None)
        else:
            os.environ["PANEL_HEADLESS_OVERRIDE"] = original_headless_override
        job.updated_at = datetime.now().isoformat(timespec="seconds")


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_download(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        if size == 0:
            return {}
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route in {"/", "/preview.html"}:
            self.send_file(ROOT / "preview.html", "text/html; charset=utf-8")
            return
        if route in {"/item-alteracao", "/item-alteracao.html"}:
            self.send_file(ROOT / "item_alteracao.html", "text/html; charset=utf-8")
            return
        if route in {"/produto-unico", "/produto-unico.html"}:
            self.send_file(ROOT / "produto_unico.html", "text/html; charset=utf-8")
            return
        if route == "/api/stores":
            self.send_json({"stores": load_store_mapping()})
            return
        if route == "/api/product-generator/options":
            self.send_json({"locals": GERADOR_LOCAIS, "fiscal_groups": GRUPOS_FISCAIS})
            return
        if route == "/api/product-generator/products":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            self.send_json({"products": buscar_produtos(query)})
            return
        if route.startswith("/api/exportacoes/"):
            filename = route.rsplit("/", 1)[-1]
            if not filename or "/" in filename or "\\" in filename:
                self.send_json({"error": "Arquivo invalido"}, HTTPStatus.BAD_REQUEST)
                return
            export_dir = ROOT / "EXPORTACOES_ZIGPAY"
            path = (export_dir / filename).resolve()
            if export_dir.resolve() not in path.parents or not path.exists():
                self.send_json({"error": "Arquivo nao encontrado"}, HTTPStatus.NOT_FOUND)
                return
            self.send_download(
                path,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            return
        if route.startswith("/api/jobs/"):
            job_id = route.rsplit("/", 1)[-1]
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                self.send_json({"error": "Tarefa nao encontrada"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json(job.__dict__)
            return
        self.send_json({"error": "Rota nao encontrada"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            payload = self.read_json()
            if route == "/api/preview-prices":
                product = str(payload.get("product", ""))
                unit_ids = [str(item) for item in payload.get("unit_ids", [])]
                stores = selected_stores(unit_ids)
                self.send_json({"rows": prices_for(product, stores)})
                return
            if route == "/api/jobs":
                action = str(payload.get("action", ""))
                job_id = uuid.uuid4().hex
                job = Job(id=job_id, action=action)
                with jobs_lock:
                    jobs[job_id] = job
                thread = threading.Thread(target=run_job, args=(job_id, payload), daemon=True)
                thread.start()
                self.send_json({"job_id": job_id}, HTTPStatus.ACCEPTED)
                return
            self.send_json({"error": "Rota nao encontrada"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    load_env_file()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Painel local em http://127.0.0.1:{PORT}/preview.html")
    if HOST in {"0.0.0.0", "::"}:
        computer_name = os.environ.get("COMPUTERNAME", "localhost")
        print(f"Tambem pode abrir pelo nome do computador: http://{computer_name}:{PORT}/preview.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
