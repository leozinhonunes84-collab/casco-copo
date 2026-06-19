from __future__ import annotations

import os
import time
from collections.abc import Callable

from playwright.sync_api import Page, sync_playwright

from sheets_prices import load_env_file, money_to_cents, open_spreadsheet, read_price_row


LogFn = Callable[[str], None]


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} nao informado")
    if value in {"seu_usuario", "sua_senha"}:
        raise ValueError(f"{name} ainda esta com o valor de exemplo no .env")
    return value


def bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "sim", "yes", "y"}


def log_default(message: str) -> None:
    print(message)


def selecionar_local(page: Page, local: str, log: LogFn = log_default) -> None:
    log(f"Selecionando LOCAL -> {local}")
    local_norm = " ".join(str(local).split())
    card = page.locator(
        f"xpath=//b[contains(normalize-space(.), '{local_norm}')]"
    ).first
    card.wait_for(timeout=15000)
    card.scroll_into_view_if_needed()
    page.wait_for_timeout(1000)
    card.click(force=True)
    page.wait_for_timeout(5000)


def abrir_menu_produtos(page: Page, log: LogFn = log_default) -> None:
    log("Abrindo MENU PRODUTOS...")
    page.locator(
        "xpath=//*[@id='zig-popup-anchor']/div/div[2]/nav/ul/li[5]/span/a"
    ).click()
    page.wait_for_timeout(2000)
    page.mouse.move(1400, 400)
    page.wait_for_timeout(500)
    page.mouse.move(900, 500)
    page.wait_for_timeout(500)
    page.mouse.move(1200, 350)
    page.wait_for_timeout(500)
    page.locator(
        'xpath=//*[@id="content-wrapper"]/div[3]/div[1]/ul/li[2]/a'
    ).click(force=True)
    page.wait_for_timeout(4000)


def buscar_produto(page: Page, produto: str, log: LogFn = log_default) -> None:
    log(f"Buscando -> {produto}")
    busca = (
        "xpath=//*[@id='content-wrapper']/div[3]/div[2]/header/"
        "div[1]/div[1]/div/div[1]/div/input"
    )
    campo = page.locator(busca)
    campo.click()
    campo.press("Control+A")
    campo.press("Backspace")
    page.wait_for_timeout(500)
    campo.fill(produto)
    page.keyboard.press("Enter")
    page.wait_for_timeout(4000)


def abrir_edicao(page: Page, log: LogFn = log_default, sku: str | None = None) -> None:
    log("Abrindo EDITAR...")
    opened = page.evaluate(
        """
        (sku) => {
            const wanted = String(sku || "").replace(/^#/, "").trim();
            const rows = [...document.querySelectorAll("table tbody tr")];
            const row = wanted
                ? rows.find((candidate) => [...candidate.querySelectorAll("td")]
                    .some((cell) => cell.innerText.replace(/^#/, "").trim() === wanted))
                : rows[0];
            const svg = row?.querySelector("td:last-child svg");
            if (!svg) return false;
            svg.dispatchEvent(new MouseEvent("click", {bubbles:true}));
            return true;
        }
        """,
        sku or "",
    )
    if not opened:
        detalhe = f" para o SKU #{sku}" if sku else ""
        raise RuntimeError(f"Acao Editar nao encontrada{detalhe}")
    page.wait_for_timeout(1500)
    page.evaluate(
        """
        () => {
            const el = [...document.querySelectorAll("span")]
                .find(e => e.innerText.trim() === "Editar");
            if (el) el.click();
        }
        """
    )
    page.wait_for_timeout(5000)
    for _ in range(8):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(300)
    page.wait_for_timeout(2000)


def limpar_e_preencher(page: Page, campo, centavos: int, log: LogFn = log_default) -> None:
    campo.wait_for(timeout=15000)
    campo.scroll_into_view_if_needed()
    page.wait_for_timeout(1500)
    for tentativa in range(5):
        try:
            campo.click(timeout=5000)
            break
        except Exception:
            log(f"  Tentando clicar novamente {tentativa + 1}")
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1000)
    campo.press("Control+A")
    campo.press("Backspace")
    campo.fill(str(centavos))
    page.wait_for_timeout(1000)


def alterar_precos(
    page: Page,
    regua_val: int,
    p_val: int,
    g_val: int,
    um_litro_val: int,
    log: LogFn = log_default,
) -> None:
    log("Alterando PRECOS...")

    xpaths = {
        "REGUA": (
            "/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            "div[2]/div/div[2]/div[2]/div[2]/div[1]/div[1]/div[2]/"
            "div[1]/div[2]/div[2]/div/div/div/input"
        ),
        "P": (
            "/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            "div[2]/div/div[2]/div[2]/div[2]/div[2]/div[1]/div[2]/"
            "div[1]/div[2]/div[2]/div/div/div/input"
        ),
        "G": (
            "/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            "div[2]/div/div[2]/div[2]/div[2]/div[3]/div[1]/div[2]/"
            "div[1]/div[2]/div[2]/div/div/div/input"
        ),
        "1L": (
            "/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            "div[2]/div/div[2]/div[2]/div[2]/div[4]/div[1]/div[2]/"
            "div[1]/div[2]/div[2]/div/div/div/input"
        ),
    }
    valores = {
        "REGUA": regua_val,
        "P": p_val,
        "G": g_val,
        "1L": um_litro_val,
    }

    for tamanho, xpath in xpaths.items():
        valor = valores[tamanho]
        log(f"  {tamanho} -> {valor} centavos")
        limpar_e_preencher(page, page.locator(f"xpath={xpath}"), valor, log)
        page.wait_for_timeout(1000)


def salvar(page: Page, log: LogFn = log_default) -> None:
    log("Salvando...")
    page.locator(
        "xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[6]/button[2]/span"
    ).click()
    page.wait_for_timeout(4000)


def fechar_modal(page: Page, log: LogFn = log_default) -> None:
    log("Fechando MODAL...")
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        page.locator(
            "xpath=//*[@id='content-wrapper']/div[3]/div[2]/div[2]/div/div/div[1]/button/span"
        ).click(force=True)
        page.wait_for_timeout(3000)
    except Exception:
        pass


def run_price_adjust_dashboard(
    produto: str,
    locais: list[str],
    manual_prices: dict[str, int] | None = None,
    log: LogFn = log_default,
    precise_skus: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    load_env_file()
    org = env_required("ZIG_ORG")
    user = env_required("ZIG_USER")
    password = env_required("ZIG_PASSWORD")
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://dashboard.zigpay.com.br").rstrip("/")

    produto = str(produto).strip().upper()
    locais = [str(local).strip().upper() for local in locais if str(local).strip()]
    if not produto:
        raise ValueError("Produto nao informado")
    if not locais:
        raise ValueError("Nenhuma unidade informada")

    linha_preco = None
    if manual_prices:
        required = ["REGUA", "P", "G", "1L"]
        missing = [key for key in required if key not in manual_prices]
        if missing:
            raise ValueError(f"Precos manuais ausentes: {', '.join(missing)}")
    else:
        spreadsheet = open_spreadsheet()
        linha_preco = read_price_row(spreadsheet, produto)

    errors: list[dict[str, str]] = []
    local_atual = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=bool_env("HEADLESS", default=False),
            slow_mo=60,
        )
        page = browser.new_page()

        log("Login...")
        page.goto(f"{dashboard_url}/login")
        page.wait_for_selector("input[name='organization']", timeout=15000)
        page.fill("input[name='organization']", org)
        page.fill("input[name='username']", user)
        page.fill("input[name='password']", password)
        page.click("button[type='submit']")
        try:
            page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
        except Exception:
            raise RuntimeError(
                "Login falhou: verifique usuario/senha/organizacao no arquivo .env "
                "(ZIG_USER, ZIG_PASSWORD, ZIG_ORG)"
            )

        for index, local in enumerate(locais, start=1):
            log(f"[{index}/{len(locais)}] {produto} | {local}")
            try:
                if manual_prices:
                    regua_val = int(manual_prices["REGUA"])
                    p_val = int(manual_prices["P"])
                    g_val = int(manual_prices["G"])
                    um_litro_val = int(manual_prices["1L"])
                elif "BOTAFOGO" in local:
                    raw_values = linha_preco[10], linha_preco[11], linha_preco[12], linha_preco[13]
                    regua_val, p_val, g_val, um_litro_val = [
                        money_to_cents(value) for value in raw_values
                    ]
                else:
                    raw_values = linha_preco[4], linha_preco[5], linha_preco[6], linha_preco[7]
                    regua_val, p_val, g_val, um_litro_val = [
                        money_to_cents(value) for value in raw_values
                    ]
                log(
                    "Precos -> "
                    f"REGUA:{regua_val} P:{p_val} G:{g_val} 1L:{um_litro_val}"
                )

                if local != local_atual:
                    page.goto(f"{dashboard_url}/")
                    page.wait_for_timeout(4000)
                    selecionar_local(page, local, log)
                    abrir_menu_produtos(page, log)
                    local_atual = local

                sku_principal = precise_skus.get("MAIN") if precise_skus else None
                buscar_produto(page, sku_principal or produto, log)
                abrir_edicao(page, log, sku_principal)
                alterar_precos(page, regua_val, p_val, g_val, um_litro_val, log)
                salvar(page, log)
                fechar_modal(page, log)

                page.reload()
                page.wait_for_timeout(6000)
                abrir_menu_produtos(page, log)
                log(f"OK -> {produto} | {local}")
            except Exception as exc:
                message = str(exc)
                log(f"ERRO -> {local}: {message}")
                errors.append({"store": local, "error": message})
                try:
                    page.screenshot(path=f"erro_ajuste_{index}.png")
                except Exception:
                    pass
                try:
                    fechar_modal(page, log)
                except Exception:
                    pass

        time.sleep(3)
        browser.close()

    return errors
