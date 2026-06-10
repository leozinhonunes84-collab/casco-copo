from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from zig_client import DEFAULT_BASE_URL, ZigClient

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "4178"))


# ── Lojas fixas ────────────────────────────────────────────────────────────────
def load_lojas() -> list[dict[str, Any]]:
    path = ROOT / os.environ.get("LOJAS_JSON", "lojas.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


# ── Zig client ─────────────────────────────────────────────────────────────────
def zig_client() -> ZigClient:
    token = os.environ.get("ZIG_API_TOKEN", "").strip()
    base_url = os.environ.get("ZIG_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    return ZigClient(token=token, base_url=base_url)


# ── Jobs ───────────────────────────────────────────────────────────────────────
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
        self.logs.append(f"{datetime.now().strftime('%H:%M:%S')} — {message}")


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()


def run_job(job_id: str, payload: dict[str, Any]) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.status = "running"
        job.log("Iniciado")

    try:
        action = job.action
        client = zig_client()
        lojas = load_lojas()

        if action == "saida_produtos":
            loja_id  = str(payload.get("loja", ""))
            dtinicio = str(payload.get("dtinicio", ""))
            dtfim    = str(payload.get("dtfim", dtinicio))
            job.log(f"Buscando saída de produtos: {loja_id} {dtinicio}→{dtfim}")
            data = client.saida_produtos(loja_id, dtinicio, dtfim)
            job.result = {"data": data, "count": len(data)}

        elif action == "faturamento":
            loja_id  = str(payload.get("loja", ""))
            dtinicio = str(payload.get("dtinicio", ""))
            dtfim    = str(payload.get("dtfim", dtinicio))
            job.log(f"Buscando faturamento: {loja_id} {dtinicio}→{dtfim}")
            data = client.faturamento(loja_id, dtinicio, dtfim)
            job.result = {"data": data}

        elif action == "todas_lojas_saida":
            dtinicio = str(payload.get("dtinicio", ""))
            dtfim    = str(payload.get("dtfim", dtinicio))
            loja_ids = payload.get("loja_ids", [l["id"] for l in lojas])
            resultados = []
            for loja_id in loja_ids:
                nome = next((l["name"] for l in lojas if l["id"] == loja_id), loja_id)
                job.log(f"Buscando: {nome}")
                try:
                    data = client.saida_produtos(loja_id, dtinicio, dtfim)
                    resultados.extend(data)
                except Exception as e:
                    job.log(f"Erro em {nome}: {e}")
            job.result = {"data": resultados, "count": len(resultados)}

        else:
            raise ValueError(f"Ação desconhecida: {action}")

        job.status = "done"
        job.log("Concluído")

    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        job.log(f"Erro: {exc}")
        job.result = {"traceback": traceback.format_exc()}
    finally:
        job.updated_at = datetime.now().isoformat(timespec="seconds")


# ── HTTP Handler ───────────────────────────────────────────────────────────────
class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size).decode("utf-8")) if size else {}

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route  = parsed.path
        params = parse_qs(parsed.query)

        def p(k: str, default: str = "") -> str:
            return params.get(k, [default])[0]

        # ── Servir HTML ──────────────────────────────────────────────────────
        if route in {"/", "/index.html", "/dashboard.html"}:
            self.send_html(ROOT / "dashboard.html")
            return

        # ── Lojas ────────────────────────────────────────────────────────────
        if route == "/api/lojas":
            self.send_json({"lojas": load_lojas()})
            return

        # ── Cardápio ─────────────────────────────────────────────────────────
        if route == "/api/cardapio":
            loja_id = p("loja")
            if not loja_id:
                self.send_json({"error": "param loja obrigatório"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                data = zig_client().cardapio(loja_id)
                self.send_json({"data": data})
            except Exception as e:
                self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            return

        # ── Saída de produtos ─────────────────────────────────────────────────
        if route == "/api/saida-produtos":
            loja_id  = p("loja")
            dtinicio = p("dtinicio")
            dtfim    = p("dtfim", dtinicio)
            if not loja_id or not dtinicio:
                self.send_json({"error": "params: loja, dtinicio"}, HTTPStatus.BAD_REQUEST)
                return
            print(f"  [Zig] saida-produtos  loja={loja_id}  {dtinicio} → {dtfim}")
            try:
                data = zig_client().saida_produtos(loja_id, dtinicio, dtfim)
                print(f"  [Zig] → {len(data)} itens OK")
                self.send_json({"data": data, "count": len(data)})
            except Exception as e:
                print(f"  [Zig] → ERRO: {e}")
                self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            return

        # ── Diagnóstico (raw + chunked) ────────────────────────────────────────
        if route == "/api/diag":
            import requests as _req

            lojas_list = load_lojas()
            loja_id  = p("loja") or (lojas_list[0]["id"] if lojas_list else "")
            dtinicio = p("dtinicio") or datetime.now().strftime("%Y-%m-%d")
            dtfim    = p("dtfim", dtinicio)
            token    = os.environ.get("ZIG_API_TOKEN", "")
            base_url = os.environ.get("ZIG_BASE_URL", DEFAULT_BASE_URL)
            api_url  = f"{base_url.rstrip('/')}/erp/saida-produtos"
            hdrs     = {
                "Authorization": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            def _norm_list(raw: Any) -> list:
                if isinstance(raw, list):
                    return raw
                if isinstance(raw, dict):
                    for k in ("data", "items", "results", "content", "records",
                              "list", "saidas", "vendas", "products", "orders",
                              "registros", "response", "sales", "movements", "salesData"):
                        if isinstance(raw.get(k), list):
                            return raw[k]
                return []

            result: dict[str, Any] = {
                "loja_id": loja_id,
                "dtinicio": dtinicio,
                "dtfim": dtfim,
            }

            # 1. Chamada RAW (sem chunk) — vai falhar se > 5 dias
            try:
                resp = _req.get(
                    api_url, headers=hdrs,
                    params={"loja": loja_id, "dtinicio": dtinicio, "dtfim": dtfim},
                    timeout=30,
                )
                result["raw_status"]  = resp.status_code
                result["raw_url"]     = resp.url
                result["raw_bytes"]   = len(resp.content)
                result["raw_preview"] = resp.text[:300]
                try:
                    rj = resp.json()
                    result["raw_json_type"] = type(rj).__name__
                    items = _norm_list(rj)
                    if items:
                        result["raw_count"]      = len(items)
                        result["raw_first_item"] = items[0]
                    elif isinstance(rj, dict):
                        result["raw_dict_keys"] = list(rj.keys())[:10]
                        result["raw_message"]   = rj.get("message") or rj.get("error") or ""
                except Exception:
                    pass
            except Exception as exc:
                result["raw_error"] = str(exc)

            # 2. Chamadas CHUNKED (igual ao fetchLoja do dashboard — 5 dias)
            try:
                s_dt = date.fromisoformat(dtinicio)
                e_dt = date.fromisoformat(dtfim)
                dias_total = (e_dt - s_dt).days + 1
                chunks: list[tuple[str, str]] = []
                cur = s_dt
                while cur <= e_dt:
                    fim_chunk = min(cur + timedelta(days=4), e_dt)
                    chunks.append((cur.isoformat(), fim_chunk.isoformat()))
                    cur = fim_chunk + timedelta(days=1)

                result["chunked_total_dias"]  = dias_total
                result["chunked_num_chunks"]  = len(chunks)
                result["chunked_chunks"]      = [{"start": a, "end": b} for a, b in chunks]

                all_rows: list = []
                chunk_results = []
                for ci, cf in chunks:
                    try:
                        cr = _req.get(
                            api_url, headers=hdrs,
                            params={"loja": loja_id, "dtinicio": ci, "dtfim": cf},
                            timeout=30,
                        )
                        rows = _norm_list(cr.json()) if cr.ok else []
                        all_rows.extend(rows)
                        chunk_results.append({
                            "chunk": f"{ci}→{cf}",
                            "status": cr.status_code,
                            "count": len(rows),
                        })
                    except Exception as ce:
                        chunk_results.append({"chunk": f"{ci}→{cf}", "error": str(ce)})

                result["chunked_results"]       = chunk_results
                result["chunked_total_records"] = len(all_rows)
                if all_rows:
                    result["chunked_first_item"] = all_rows[0]

            except Exception as ce:
                result["chunked_error"] = str(ce)

            self.send_json(result)
            return

        # ── Faturamento ───────────────────────────────────────────────────────
        if route == "/api/faturamento":
            loja_id  = p("loja")
            dtinicio = p("dtinicio")
            dtfim    = p("dtfim", dtinicio)
            if not loja_id or not dtinicio:
                self.send_json({"error": "params: loja, dtinicio"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                data = zig_client().faturamento(loja_id, dtinicio, dtfim)
                self.send_json({"data": data})
            except Exception as e:
                self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            return

        # ── Jobs ──────────────────────────────────────────────────────────────
        if route.startswith("/api/jobs/"):
            job_id = route.rsplit("/", 1)[-1]
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                self.send_json({"error": "Job não encontrado"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json(job.__dict__)
            return

        self.send_json({"error": "Rota não encontrada"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            payload = self.read_json()

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

            self.send_json({"error": "Rota não encontrada"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


# ── Main ───────────────────────────────────────────────────────────────────────
def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_env()
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, PORT), AppHandler)
    print(f"\n  🍺 Brewteco API — http://{host}:{PORT}")
    print(f"  📊 Dashboard    — http://{host}:{PORT}/dashboard.html")
    print(f"  📋 Lojas        — http://{host}:{PORT}/api/lojas")
    print(f"\n  Pressione Ctrl+C para parar.\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
