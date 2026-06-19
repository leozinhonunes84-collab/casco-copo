from __future__ import annotations

import os
import time

from playwright.sync_api import Page, sync_playwright

from sheets_prices import (
    get_prices_for_local,
    load_env_file,
    open_spreadsheet,
    read_cadastro,
    read_price_row,
)


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


def digitar_preco(page: Page, xpath: str, centavos: int) -> None:
    campo = page.locator(f"xpath={xpath}")
    campo.click()
    page.wait_for_timeout(300)
    page.keyboard.press("Control+a")
    page.wait_for_timeout(100)
    page.keyboard.press("Delete")
    page.wait_for_timeout(100)
    page.keyboard.type(str(centavos))
    page.wait_for_timeout(300)


def selecionar_local(page: Page, local: str) -> None:
    local_norm = " ".join(str(local).strip().upper().split())
    antigo = page.locator(f"xpath=//b[@title='{local_norm}' or contains(normalize-space(.), '{local_norm}')]").first
    try:
        antigo.wait_for(state="visible", timeout=5000)
        antigo.scroll_into_view_if_needed(timeout=5000)
        antigo.click(force=True, timeout=5000)
        page.wait_for_timeout(2000)
        return
    except Exception:
        pass

    alvo = page.evaluate(
        """
        (local) => {
            const normalize = (value) => (value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toUpperCase();
            const localKey = normalize(local);
            const visible = (el) => !!(
                el
                && (el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                && getComputedStyle(el).visibility !== "hidden"
                && getComputedStyle(el).display !== "none"
            );
            const textOf = (el) => normalize([
                el.innerText,
                el.textContent,
                el.getAttribute("title"),
                el.getAttribute("aria-label"),
            ].filter(Boolean).join(" "));
            const candidatos = [...document.querySelectorAll("b, span, p, div, button, a")]
                .filter((el) => visible(el) && textOf(el).includes(localKey))
                .sort((a, b) => textOf(a).length - textOf(b).length);
            for (const candidato of candidatos) {
                const clicavel = candidato.closest("button, a, [role='button'], li, div") || candidato;
                const box = clicavel.getBoundingClientRect();
                if (box.width <= 0 || box.height <= 0) continue;
                return {
                    ok: true,
                    x: box.left + box.width / 2,
                    y: box.top + box.height / 2,
                    text: textOf(candidato),
                };
            }
            return { ok: false };
        }
        """,
        local_norm,
    )
    if not alvo.get("ok"):
        raise RuntimeError(f"Local nao encontrado na tela: {local_norm}")

    page.mouse.click(float(alvo["x"]), float(alvo["y"]))
    page.wait_for_timeout(2000)


def editar_produto_no_local(
    page: Page,
    *,
    dashboard_url: str,
    local: str,
    produto: str,
    valores: list[tuple[str, int]],
    sku_principal: str | None = None,
) -> None:
    print(f"\n{'=' * 45}")
    print(f"  PROCESSANDO LOCAL: {local}")
    print(f"{'=' * 45}")

    print("Voltando ao dashboard...")
    page.goto(dashboard_url)
    page.wait_for_timeout(4000)

    print(f"Selecionando LOCAL: {local}...")
    selecionar_local(page, local)

    print("Abrindo MENU PRODUTOS...")
    page.locator("xpath=//*[@id='zig-popup-anchor']/div/div[2]/nav/ul/li[5]/span/a").click()
    page.wait_for_timeout(2000)

    page.mouse.move(1400, 400)
    page.wait_for_timeout(1000)
    page.mouse.move(900, 500)
    page.wait_for_timeout(1000)
    page.mouse.move(1200, 350)
    page.wait_for_timeout(1000)

    print("Clicando em PRODUTOS...")
    page.locator('xpath=//*[@id="content-wrapper"]/div[3]/div[1]/ul/li[2]/a').click(force=True)
    page.wait_for_timeout(2000)

    termo_busca = sku_principal or produto
    print(f"Buscando produto: {termo_busca}...")
    busca_input = "xpath=//*[@id='content-wrapper']/div[3]/div[2]/header/div[1]/div[1]/div/div[1]/div/input"
    page.fill(busca_input, "")
    page.fill(busca_input, termo_busca)
    page.keyboard.press("Enter")
    page.wait_for_timeout(4000)

    print("Abrindo EDITAR...")
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
        sku_principal or "",
    )
    if not opened:
        detalhe = f" para o SKU #{sku_principal}" if sku_principal else ""
        raise RuntimeError(f"Acao Editar nao encontrada{detalhe}")
    page.wait_for_timeout(1000)
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

    print("Ativando MONTAVEL...")
    page.locator(
        "xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[1]/"
        "div[2]/form/div[2]/div[4]/div[2]/div/button"
    ).click()
    page.wait_for_timeout(2000)

    print("Configurando CATEGORIA...")
    page.fill(
        "xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
        "div[2]/div/div[2]/div[2]/div[1]/div[2]/div/div[2]/div/div/input",
        "CHOPE",
    )
    page.locator(
        "xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
        "div[2]/div/div[2]/div[2]/div[1]/div[3]/div[1]/div[2]/div/div"
    ).click()
    page.keyboard.press("Enter")

    print("Preenchendo CAMPOS FIXOS...")
    page.fill(
        "xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
        "div[2]/div/div[2]/div[2]/div[1]/div[3]/div[2]/div/div[1]/"
        "div[2]/div/div/div/input",
        "1",
    )
    page.fill(
        "xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
        "div[2]/div/div[2]/div[2]/div[1]/div[3]/div[2]/div/div[2]/"
        "div[2]/div/div/div/input",
        "1",
    )

    print("Configurando TAMANHOS...")
    for idx, (nome, valor) in enumerate(valores, start=1):
        print(f"  -> Tamanho {idx}: {nome} | {valor} centavos")

        page.locator(
            f"xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            f"div[2]/div/div[2]/div[2]/div[2]/div[{idx}]/div[1]/div[2]/"
            f"div[1]/div[1]/div[2]/div/div[1]/span[2]"
        ).click()
        page.keyboard.type(nome)
        page.keyboard.press("Enter")

        page.fill(
            f"xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            f"div[2]/div/div[2]/div[2]/div[2]/div[{idx}]/div[1]/div[2]/"
            f"div[2]/div[1]/div[2]/div/div/div/input",
            "1",
        )
        page.fill(
            f"xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            f"div[2]/div/div[2]/div[2]/div[2]/div[{idx}]/div[1]/div[2]/"
            f"div[2]/div[2]/div[2]/div/div/div[1]/div/input",
            "1",
        )

        xpath_preco = (
            f"/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
            f"div[2]/div/div[2]/div[2]/div[2]/div[{idx}]/div[1]/div[2]/"
            f"div[1]/div[2]/div[2]/div/div/div/input"
        )
        digitar_preco(page, xpath_preco, valor)

        if idx < len(valores):
            page.locator(
                f"xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[4]/"
                f"div[2]/div/div[2]/div[2]/div[2]/div[{idx + 1}]/button/span[2]"
            ).click()
            page.wait_for_timeout(1500)

    print("Marcando FLAGS...")
    checkboxes = page.locator("input[id^='modification-']")
    for i in range(checkboxes.count()):
        checkbox = checkboxes.nth(i)
        if not checkbox.is_checked():
            checkbox.click(force=True)
            page.wait_for_timeout(200)

    print("Salvando...")
    page.locator(
        "xpath=/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[6]/button[2]/span"
    ).click()
    page.wait_for_timeout(4000)

    print("Fechando modal...")
    page.locator(
        "xpath=//*[@id='content-wrapper']/div[3]/div[2]/div[2]/div/div/div[1]/button/span"
    ).click(force=True)
    page.wait_for_timeout(3000)

    print(f"Local '{local}' concluido!")


def run_dashboard_update(
    produto: str | None = None,
    locais: list[str] | None = None,
    manual_prices: dict[str, int] | None = None,
    precise_skus: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    org = env_required("ZIG_ORG")
    user = env_required("ZIG_USER")
    password = env_required("ZIG_PASSWORD")
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://dashboard.zigpay.com.br").rstrip("/")

    spreadsheet = open_spreadsheet()
    if produto and locais is not None:
        produto = produto.strip().upper()
        locais = [local.strip().upper() for local in locais if local.strip()]
    else:
        cadastro = read_cadastro(spreadsheet)
        produto = cadastro.produto
        locais = cadastro.locais

    if not produto:
        raise ValueError("Produto nao informado")
    if not locais:
        raise ValueError("Nenhuma unidade informada")

    price_row = None
    if manual_prices:
        required = ["REGUA", "P", "G", "1L"]
        missing = [key for key in required if key not in manual_prices]
        if missing:
            raise ValueError(f"Precos manuais ausentes: {', '.join(missing)}")
    else:
        price_row = read_price_row(spreadsheet, produto)

    print("=====================================")
    print("  INICIANDO AUTOMACAO ZIGPAY")
    print("=====================================")
    print(f"Chope: {produto}")
    print(f"Locais selecionados ({len(locais)}): {locais}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=bool_env("HEADLESS", default=False),
            slow_mo=60,
        )
        page = browser.new_page()

        print("Login...")
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

        errors: list[tuple[str, str]] = []

        for index, local in enumerate(locais, start=1):
            print(f"\n[{index}/{len(locais)}] Iniciando local: {local}")
            try:
                if manual_prices:
                    valores = [
                        (f"{produto} REGUA", int(manual_prices["REGUA"])),
                        (f"{produto} P", int(manual_prices["P"])),
                        (f"{produto} G", int(manual_prices["G"])),
                        (f"{produto} 1L", int(manual_prices["1L"])),
                    ]
                else:
                    prices = get_prices_for_local(price_row, local)
                    valores = prices.as_rows(produto)
                print(
                    "Precos -> "
                    + " | ".join(f"{nome}: {valor}" for nome, valor in valores)
                )
                editar_produto_no_local(
                    page,
                    dashboard_url=dashboard_url,
                    local=local,
                    produto=produto,
                    valores=valores,
                    sku_principal=precise_skus.get("MAIN") if precise_skus else None,
                )
            except Exception as exc:
                print(f"ERRO no local '{local}': {exc}")
                errors.append((local, str(exc)))
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1000)
                    page.goto(dashboard_url)
                    page.wait_for_timeout(4000)
                except Exception:
                    pass

        time.sleep(3)
        browser.close()

    print("\n=====================================")
    if not errors:
        print(f"  TODOS OS {len(locais)} LOCAIS FINALIZADOS COM SUCESSO!")
    else:
        print(f"  CONCLUIDO COM {len(errors)} ERRO(S):")
        for local, message in errors:
            print(f"  {local}: {message}")
    print("=====================================")
    return errors


def main() -> None:
    load_env_file()
    run_dashboard_update()


if __name__ == "__main__":
    main()
