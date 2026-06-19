from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable

from playwright.sync_api import Locator, Page, sync_playwright

from sheets_prices import load_env_file


LogFn = Callable[[str], None]


UNIDADES_CONHECIDAS = [
    "BREWTECO GAVEA",
    "BREWTECO BOTAFOGO",
    "BREWTECO LEBLON",
    "BREWTECO MORRO DA URCA",
    "BREWTECO ROSAS",
    "BREWTECO TIJUCA",
    "BREWTECO FERRADURA",
    "RUFI.BAR",
    "BREWTECO LARANJEIRAS",
]


def log_default(message: str) -> None:
    print(message)


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


def first_visible(locator: Locator, timeout: int = 5000) -> Locator | None:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return locator.first
    except Exception:
        return None


def localizar_elemento(page: Page, xpath: str, timeout: int = 5000) -> Locator | None:
    locator = first_visible(page.locator(f"xpath={xpath}"), timeout=timeout)
    if locator:
        return locator

    for frame in page.frames:
        locator = first_visible(frame.locator(f"xpath={xpath}"), timeout=1500)
        if locator:
            return locator
    return None


def click_locator(locator: Locator, page: Page, log: LogFn = log_default) -> None:
    locator.scroll_into_view_if_needed(timeout=10000)
    try:
        locator.click(timeout=5000)
    except Exception:
        handle = locator.element_handle(timeout=5000)
        if not handle:
            raise
        page.evaluate("(el) => el.click()", handle)


def login(page: Page, log: LogFn = log_default) -> None:
    org = env_required("ZIG_ORG")
    user = env_required("ZIG_USER")
    password = env_required("ZIG_PASSWORD")
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://dashboard.zigpay.com.br").rstrip("/")

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


def abrir_cadastro_base(page: Page, log: LogFn = log_default) -> None:
    xpath_hr = '//*[@id="zig-popup-anchor"]/div/div[2]/nav/hr'
    elemento_hr = localizar_elemento(page, xpath_hr)
    if elemento_hr:
        elemento_hr.hover(timeout=5000)
        log("Hover realizado sobre o separador do menu lateral.")
        page.wait_for_timeout(1000)
    else:
        log("Separador do menu lateral nao encontrado.")

    xpath_pai = '//*[@id="zig-popup-anchor"]/div/div[2]/nav/ul/li[3]/span/div[1]'
    elemento_pai = localizar_elemento(page, xpath_pai)
    if not elemento_pai:
        raise RuntimeError("Menu pai nao encontrado")
    click_locator(elemento_pai, page, log)
    log("Clique no menu pai realizado.")
    page.wait_for_timeout(1000)

    xpath_item = '//*[@id="zig-popup-anchor"]/div/div[2]/nav/ul/li[3]/span/div[2]/div/ul/li[1]/a'
    elemento_item = localizar_elemento(page, xpath_item)
    if not elemento_item:
        raise RuntimeError("Submenu Cadastro Base de Produtos nao encontrado")
    click_locator(elemento_item, page, log)
    log("Clique no submenu realizado.")
    page.mouse.move(360, 240)
    log("Mouse movido para fora do menu lateral.")
    page.wait_for_timeout(2500)


def pesquisar_chope(page: Page, produto: str, log: LogFn = log_default) -> None:
    campo = localizar_elemento(page, "//input[@placeholder='Pesquisar']", timeout=10000)
    if not campo:
        raise RuntimeError("Campo Pesquisar nao encontrado")

    campo.fill("")
    page.wait_for_timeout(300)
    campo.type(".", delay=70)
    page.wait_for_timeout(500)
    campo.press("Backspace")
    page.wait_for_timeout(300)
    campo.type(produto, delay=90)
    log(f"Campo Pesquisar preenchido: {produto}")
    page.wait_for_timeout(1200)


def selecionar_produto(page: Page, log: LogFn = log_default) -> None:
    elemento = localizar_elemento(page, '//*[@id="select-all-from-0-0"]', timeout=10000)
    if not elemento:
        raise RuntimeError("Elemento select-all-from-0-0 nao encontrado")
    click_locator(elemento, page, log)
    log("Elemento select-all-from-0-0 selecionado.")
    page.wait_for_timeout(1000)


def abrir_modal_liberacao(page: Page, log: LogFn = log_default) -> None:
    botao = localizar_elemento(
        page,
        '//*[@id="content-wrapper"]/div[4]/div[2]/div[1]/div[2]/button[4]',
        timeout=10000,
    )
    if not botao:
        raise RuntimeError("Botao de liberacao nao encontrado")
    click_locator(botao, page, log)
    log("Botao de liberacao clicado.")
    page.wait_for_timeout(1500)


def normalizar_unidade(nome: str) -> str:
    nome = " ".join(str(nome).strip().upper().split())
    for prefixo in ("BREWTECO ",):
        if nome.startswith(prefixo):
            return nome.removeprefix(prefixo)
    return nome


def normalizar_lista_unidades(unidades: list[str]) -> list[str]:
    return [" ".join(str(unidade).strip().upper().split()) for unidade in unidades if str(unidade).strip()]


def _selecionar_locais_exatos_legacy(page: Page, unidades: list[str], log: LogFn = log_default) -> list[str]:
    desejadas = normalizar_lista_unidades(unidades)
    if not desejadas:
        raise ValueError("Selecione pelo menos uma unidade para liberar")

    desconhecidas = [unidade for unidade in desejadas if unidade not in UNIDADES_CONHECIDAS]
    if desconhecidas:
        raise ValueError(f"Unidade desconhecida: {', '.join(desconhecidas)}")

    log("Ajustando campo Locais para manter apenas as unidades selecionadas...")
    resultado = {"ok": False, "reason": "Campo Locais ainda nao validado", "selected": []}
    for _ in range(5):
        resultado = page.evaluate(
            """
            (desejadas) => {
            const conhecidas = [
                "BREWTECO GAVEA",
                "BREWTECO BOTAFOGO",
                "BREWTECO LEBLON",
                "BREWTECO MORRO DA URCA",
                "BREWTECO ROSAS",
                "BREWTECO TIJUCA",
                "BREWTECO FERRADURA",
                "RUFI.BAR",
                "BREWTECO LARANJEIRAS",
            ];
            const normalize = (value) => (value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/Ã—/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toUpperCase();
            const visible = (el) => !!(
                el
                && (el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                && getComputedStyle(el).visibility !== "hidden"
                && getComputedStyle(el).display !== "none"
            );
            const wanted = new Set(desejadas.map(normalize));
            const wantedKnown = conhecidas.filter((unidade) => wanted.has(normalize(unidade)));
            const candidates = [...document.querySelectorAll("label, div, span")]
                .filter((el) => visible(el) && normalize(el.innerText) === "LOCAIS");
            const label = candidates[0];
            if (!label) return { ok: false, reason: "Campo Locais nao encontrado", selected: [] };

            let field = null;
            let current = label;
            for (let depth = 0; current && depth < 8; depth += 1) {
                const controls = [...current.querySelectorAll(
                    ".ant-select, [role='combobox'], input, textarea"
                )].filter(visible);
                if (controls.length) {
                    field = current;
                    break;
                }
                current = current.parentElement;
            }
            if (!field) {
                let sibling = label.nextElementSibling;
                while (sibling && !field) {
                    const controls = [...sibling.querySelectorAll(
                        ".ant-select, [role='combobox'], input, textarea"
                    )].filter(visible);
                    if (controls.length) field = sibling;
                    sibling = sibling.nextElementSibling;
                }
            }
            if (!field) return { ok: false, reason: "Controle de Locais nao encontrado", selected: [] };

            const selectedNames = () => {
                const text = normalize(field.innerText);
                return conhecidas.filter((unidade) => text.includes(normalize(unidade)));
            };

            for (let attempt = 0; attempt < 8; attempt += 1) {
                let changed = false;
                const selected = selectedNames();
                for (const unidade of selected) {
                    if (wanted.has(normalize(unidade))) continue;
                    const nodes = [...field.querySelectorAll("*")]
                        .filter((el) => visible(el) && normalize(el.innerText).includes(normalize(unidade)));
                    const tag = nodes
                        .sort((a, b) => a.innerText.length - b.innerText.length)[0];
                    if (!tag) continue;
                    const close = tag.querySelector(
                        ".ant-select-selection-item-remove, [aria-label='close'], [aria-label='Close'], svg, button"
                    );
                    if (close) {
                        close.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
                        close.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                    } else {
                        tag.dispatchEvent(new KeyboardEvent("keydown", {
                            key: "Backspace",
                            code: "Backspace",
                            bubbles: true,
                        }));
                    }
                    changed = true;
                }
                if (!changed) break;
            }

            const selected = selectedNames();
            const missing = wantedKnown.filter(
                (unidade) => !selected.some((item) => normalize(item) === normalize(unidade))
            );
            if (missing.length) {
                return {
                    ok: false,
                    reason: `Unidade(s) selecionada(s) ausente(s) no modal: ${missing.join(", ")}`,
                    selected,
                };
            }

            const extra = selected.filter((unidade) => !wanted.has(normalize(unidade)));
            return {
                ok: extra.length === 0,
                reason: extra.length ? `Unidade(s) indevida(s) ainda marcada(s): ${extra.join(", ")}` : "",
                selected,
            };
            }
            """,
            desejadas,
        )
        if resultado.get("ok"):
            break
        page.wait_for_timeout(800)

    selecionadas = normalizar_lista_unidades(resultado.get("selected", []))
    if not resultado.get("ok"):
        raise RuntimeError(
            f"Nao foi possivel ajustar Locais exatamente. {resultado.get('reason')}. "
            f"Selecionadas no modal: {', '.join(selecionadas) or 'nenhuma'}"
        )

    log(f"Locais confirmados: {', '.join(selecionadas)}")
    return selecionadas


def _selecionar_locais_exatos_js_click(page: Page, unidades: list[str], log: LogFn = log_default) -> list[str]:
    desejadas = normalizar_lista_unidades(unidades)
    if not desejadas:
        raise ValueError("Selecione pelo menos uma unidade para liberar")

    desconhecidas = [unidade for unidade in desejadas if unidade not in UNIDADES_CONHECIDAS]
    if desconhecidas:
        raise ValueError(f"Unidade desconhecida: {', '.join(desconhecidas)}")

    log("Ajustando campo Locais para manter apenas as unidades selecionadas...")
    resultado = {"ok": False, "reason": "Campo Locais ainda nao validado", "selected": []}
    for _ in range(3):
        resultado = page.evaluate(
            """
            async ({ desejadas, conhecidas }) => {
                const normalize = (value) => (value || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/Ã—/g, "")
                    .replace(/×/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toUpperCase();
                const unitKey = (value) => normalize(value).replace(/^BREWTECO\\s+/, "");
                const textOf = (el) => normalize([
                    el.innerText,
                    el.textContent,
                    el.getAttribute("title"),
                    el.getAttribute("aria-label"),
                    el.getAttribute("value"),
                    el.getAttribute("placeholder"),
                ].filter(Boolean).join(" "));
                const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const visible = (el) => !!(
                    el
                    && (el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                    && getComputedStyle(el).visibility !== "hidden"
                    && getComputedStyle(el).display !== "none"
                );
                const wanted = new Set(desejadas.map(unitKey));
                const wantedKnown = conhecidas.filter((unidade) => wanted.has(unitKey(unidade)));
                const modal = [...document.querySelectorAll(
                    "[role='dialog'], .ant-modal, .ant-modal-content, .ant-modal-wrap, .modal, div"
                )]
                    .filter((el) => visible(el)
                        && textOf(el).includes("SELECIONAR LOCAIS")
                        && el.querySelector("input")
                        && el.querySelector("[role='switch'], .ant-switch, input[type='checkbox']"))
                    .sort((a, b) => textOf(a).length - textOf(b).length)[0];
                if (!modal) return { ok: false, reason: "Modal Selecionar locais nao encontrado", selected: [] };

                const search = [...modal.querySelectorAll("input")]
                    .filter((el) => visible(el) && textOf(el).includes("PESQUISAR LOCAIS"))[0]
                    || [...modal.querySelectorAll("input")].filter(visible)[0];
                if (!search) return { ok: false, reason: "Campo Pesquisar locais nao encontrado", selected: [] };

                const setInputValue = async (input, value) => {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
                    if (setter) setter.call(input, value);
                    else input.value = value;
                    input.focus();
                    input.dispatchEvent(new InputEvent("input", { bubbles: true, data: value, inputType: "insertText" }));
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                    await wait(350);
                };
                const clickElement = async (el) => {
                    const target = el.closest?.("[role='switch'], .ant-switch, button, label") || el;
                    target.scrollIntoView({ block: "center", inline: "nearest" });
                    target.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, pointerType: "mouse" }));
                    target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
                    target.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, pointerType: "mouse" }));
                    target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
                    target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                    target.click?.();
                    await wait(350);
                };
                const optionMatches = (el, unidade) => {
                    const text = textOf(el);
                    return text.includes(normalize(unidade)) || text.includes(unitKey(unidade));
                };
                const switchState = (sw) => {
                    const input = sw.matches("input") ? sw : sw.querySelector("input");
                    if (input) return !!input.checked;
                    if (sw.getAttribute("aria-checked") === "true") return true;
                    if (sw.getAttribute("aria-checked") === "false") return false;
                    return String(sw.className).includes("checked");
                };
                const findSwitchFor = (unidade) => {
                    const labels = [...modal.querySelectorAll("span, div, label, p")]
                        .filter((el) => visible(el) && optionMatches(el, unidade) && textOf(el).length <= 120)
                        .sort((a, b) => textOf(a).length - textOf(b).length);
                    for (const label of labels) {
                        let current = label;
                        for (let depth = 0; current && depth < 7; depth += 1) {
                            const switches = [...current.querySelectorAll(
                                "[role='switch'], .ant-switch, input[type='checkbox']"
                            )].filter(visible);
                            if (switches.length) return switches[0];
                            current = current.parentElement;
                        }

                        const parent = label.parentElement;
                        const siblings = parent ? [
                            parent.previousElementSibling,
                            parent.nextElementSibling,
                            parent.parentElement?.previousElementSibling,
                        ].filter(Boolean) : [];
                        for (const sibling of siblings) {
                            if (sibling.matches?.("[role='switch'], .ant-switch, input[type='checkbox']")) return sibling;
                            const switches = [...sibling.querySelectorAll(
                                "[role='switch'], .ant-switch, input[type='checkbox']"
                            )].filter(visible);
                            if (switches.length) return switches[0];
                        }
                    }
                    return null;
                };
                const setUnit = async (unidade, shouldBeOn) => {
                    await setInputValue(search, unitKey(unidade));
                    const sw = findSwitchFor(unidade);
                    if (!sw) {
                        return {
                            ok: false,
                            reason: `Unidade nao encontrada no modal: ${unidade}`,
                            selected: [],
                        };
                    }
                    for (let attempt = 0; attempt < 3 && switchState(sw) !== shouldBeOn; attempt += 1) {
                        await clickElement(sw);
                    }
                    if (switchState(sw) !== shouldBeOn) {
                        return {
                            ok: false,
                            reason: `Switch nao mudou para ${shouldBeOn ? "ativo" : "inativo"}: ${unidade}`,
                            selected: [],
                        };
                    }
                    return { ok: true };
                };
                const readUnit = async (unidade) => {
                    await setInputValue(search, unitKey(unidade));
                    const sw = findSwitchFor(unidade);
                    return sw && switchState(sw) ? unidade : null;
                };

                for (const unidade of conhecidas) {
                    const result = await setUnit(unidade, wanted.has(unitKey(unidade)));
                    if (!result.ok) return result;
                }

                const selected = [];
                for (const unidade of conhecidas) {
                    const selectedUnit = await readUnit(unidade);
                    if (selectedUnit) selected.push(selectedUnit);
                }
                await setInputValue(search, "");

                const missing = wantedKnown.filter(
                    (unidade) => !selected.some((item) => unitKey(item) === unitKey(unidade))
                );
                if (missing.length) {
                    return {
                        ok: false,
                        reason: `Unidade(s) selecionada(s) ausente(s) no modal: ${missing.join(", ")}`,
                        selected,
                    };
                }

                const extra = selected.filter((unidade) => !wanted.has(unitKey(unidade)));
                return {
                    ok: extra.length === 0,
                    reason: extra.length ? `Unidade(s) indevida(s) ainda marcada(s): ${extra.join(", ")}` : "",
                    selected,
                };
            }
            """,
            {"desejadas": desejadas, "conhecidas": UNIDADES_CONHECIDAS},
        )
        if resultado.get("ok"):
            break
        page.wait_for_timeout(800)

    selecionadas = normalizar_lista_unidades(resultado.get("selected", []))
    if not resultado.get("ok"):
        try:
            page.screenshot(path="debug_liberar_chope_locais.png", full_page=True)
            log("Screenshot de debug salvo em debug_liberar_chope_locais.png")
        except Exception:
            pass
        raise RuntimeError(
            f"Nao foi possivel ajustar Locais exatamente. {resultado.get('reason')}. "
            f"Selecionadas no modal: {', '.join(selecionadas) or 'nenhuma'}"
        )

    log(f"Locais confirmados: {', '.join(selecionadas)}")
    return selecionadas


def selecionar_locais_exatos(page: Page, unidades: list[str], log: LogFn = log_default) -> list[str]:
    desejadas = normalizar_lista_unidades(unidades)
    if not desejadas:
        raise ValueError("Selecione pelo menos uma unidade para liberar")

    desconhecidas = [unidade for unidade in desejadas if unidade not in UNIDADES_CONHECIDAS]
    if desconhecidas:
        raise ValueError(f"Unidade desconhecida: {', '.join(desconhecidas)}")

    def localizar_switch(unidade: str) -> dict[str, object]:
        return page.evaluate(
            """
            async (unidade) => {
                const normalize = (value) => (value || "")
                    .normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/Ã—/g, "")
                    .replace(/×/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toUpperCase();
                const unitKey = (value) => normalize(value).replace(/^BREWTECO\\s+/, "");
                const textOf = (el) => normalize([
                    el.innerText,
                    el.textContent,
                    el.getAttribute("title"),
                    el.getAttribute("aria-label"),
                    el.getAttribute("value"),
                    el.getAttribute("placeholder"),
                ].filter(Boolean).join(" "));
                const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const visible = (el) => !!(
                    el
                    && (el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                    && getComputedStyle(el).visibility !== "hidden"
                    && getComputedStyle(el).display !== "none"
                );
                const modal = [...document.querySelectorAll(
                    "[role='dialog'], .ant-modal, .ant-modal-content, .ant-modal-wrap, .modal, div"
                )]
                    .filter((el) => visible(el)
                        && textOf(el).includes("SELECIONAR LOCAIS")
                        && el.querySelector("input")
                        && el.querySelector("[role='switch'], .ant-switch, input[type='checkbox'], [class*='switch']"))
                    .sort((a, b) => textOf(a).length - textOf(b).length)[0];
                if (!modal) return { ok: false, reason: "Modal Selecionar locais nao encontrado" };

                const search = [...modal.querySelectorAll("input")]
                    .filter((el) => visible(el) && textOf(el).includes("PESQUISAR LOCAIS"))[0]
                    || [...modal.querySelectorAll("input")].filter(visible)[0];
                if (!search) return { ok: false, reason: "Campo Pesquisar locais nao encontrado" };

                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
                if (setter) setter.call(search, unitKey(unidade));
                else search.value = unitKey(unidade);
                search.focus();
                search.dispatchEvent(new InputEvent("input", { bubbles: true, data: unitKey(unidade), inputType: "insertText" }));
                search.dispatchEvent(new Event("change", { bubbles: true }));
                await wait(450);

                const matchesUnit = (el) => {
                    const text = textOf(el);
                    return text.includes(normalize(unidade)) || text.includes(unitKey(unidade));
                };
                const stateOf = (sw) => {
                    const input = sw.matches("input") ? sw : sw.querySelector("input");
                    if (input) return !!input.checked;
                    if (sw.getAttribute("aria-checked") === "true") return true;
                    if (sw.getAttribute("aria-checked") === "false") return false;
                    return String(sw.className).includes("checked");
                };
                const labels = [...modal.querySelectorAll("span, div, label, p")]
                    .filter((el) => visible(el) && matchesUnit(el) && textOf(el).length <= 120)
                    .sort((a, b) => textOf(a).length - textOf(b).length);
                for (const label of labels) {
                    let current = label;
                    for (let depth = 0; current && depth < 7; depth += 1) {
                        const switches = [...current.querySelectorAll(
                            "[role='switch'], .ant-switch, input[type='checkbox'], [class*='switch']"
                        )].filter(visible);
                        if (switches.length) {
                            const sw = switches[0].closest?.("[role='switch'], .ant-switch, button, [class*='switch']") || switches[0];
                            const box = sw.getBoundingClientRect();
                            return {
                                ok: true,
                                checked: stateOf(sw),
                                x: box.left + box.width / 2,
                                y: box.top + box.height / 2,
                            };
                        }
                        current = current.parentElement;
                    }

                    const parent = label.parentElement;
                    const siblings = parent ? [
                        parent.previousElementSibling,
                        parent.nextElementSibling,
                        parent.parentElement?.previousElementSibling,
                    ].filter(Boolean) : [];
                    for (const sibling of siblings) {
                        const candidates = sibling.matches?.("[role='switch'], .ant-switch, input[type='checkbox'], [class*='switch']")
                            ? [sibling]
                            : [...sibling.querySelectorAll("[role='switch'], .ant-switch, input[type='checkbox'], [class*='switch']")];
                        const switches = candidates.filter(visible);
                        if (switches.length) {
                            const sw = switches[0].closest?.("[role='switch'], .ant-switch, button, [class*='switch']") || switches[0];
                            const box = sw.getBoundingClientRect();
                            return {
                                ok: true,
                                checked: stateOf(sw),
                                x: box.left + box.width / 2,
                                y: box.top + box.height / 2,
                            };
                        }
                    }
                }
                return { ok: false, reason: `Unidade nao encontrada no modal: ${unidade}` };
            }
            """,
            unidade,
        )

    log("Ajustando campo Locais para manter apenas as unidades selecionadas...")
    desejadas_set = {normalizar_unidade(unidade) for unidade in desejadas}
    for unidade in UNIDADES_CONHECIDAS:
        deve_ativar = normalizar_unidade(unidade) in desejadas_set
        info = localizar_switch(unidade)
        if not info.get("ok"):
            raise RuntimeError(
                f"Nao foi possivel ajustar Locais exatamente. {info.get('reason')}. "
                "Selecionadas no modal: nenhuma"
            )

        for _ in range(3):
            if bool(info.get("checked")) == deve_ativar:
                break
            page.mouse.click(float(info["x"]), float(info["y"]))
            page.wait_for_timeout(450)
            info = localizar_switch(unidade)

        if bool(info.get("checked")) != deve_ativar:
            estado = "ativo" if deve_ativar else "inativo"
            raise RuntimeError(
                f"Nao foi possivel ajustar Locais exatamente. Switch nao mudou para {estado}: {unidade}. "
                "Selecionadas no modal: nenhuma"
            )

    selecionadas = []
    for unidade in UNIDADES_CONHECIDAS:
        info = localizar_switch(unidade)
        if info.get("ok") and info.get("checked"):
            selecionadas.append(unidade)

    faltantes = [unidade for unidade in desejadas if normalizar_unidade(unidade) not in {normalizar_unidade(item) for item in selecionadas}]
    extras = [unidade for unidade in selecionadas if normalizar_unidade(unidade) not in desejadas_set]
    if faltantes or extras:
        try:
            page.screenshot(path="debug_liberar_chope_locais.png", full_page=True)
            log("Screenshot de debug salvo em debug_liberar_chope_locais.png")
        except Exception:
            pass
        motivo = []
        if faltantes:
            motivo.append(f"Unidade(s) selecionada(s) ausente(s) no modal: {', '.join(faltantes)}")
        if extras:
            motivo.append(f"Unidade(s) indevida(s) ainda marcada(s): {', '.join(extras)}")
        raise RuntimeError(
            f"Nao foi possivel ajustar Locais exatamente. {'; '.join(motivo)}. "
            f"Selecionadas no modal: {', '.join(selecionadas) or 'nenhuma'}"
        )

    log(f"Locais confirmados: {', '.join(selecionadas)}")
    return selecionadas


def salvar(page: Page, dry_run: bool, log: LogFn = log_default) -> None:
    xpath_salvar = "/html/body/div[2]/div/div[2]/div/div[2]/div[2]/div/div[2]/button[2]"
    botao = localizar_elemento(page, xpath_salvar, timeout=10000)
    if not botao:
        raise RuntimeError("Botao Salvar nao encontrado")
    if dry_run:
        log("Modo teste: botao Salvar localizado, mas nao foi clicado.")
        return
    click_locator(botao, page, log)
    log("Botao Salvar clicado.")
    page.wait_for_timeout(1500)


def run_liberar_chope_dashboard(
    produto: str,
    unidades: list[str] | None = None,
    *,
    dry_run: bool = True,
    log: LogFn = log_default,
) -> dict[str, object]:
    load_env_file()
    produto = str(produto).strip().upper()
    unidades = [str(unidade).strip().upper() for unidade in (unidades or []) if str(unidade).strip()]
    if not produto:
        raise ValueError("Produto nao informado")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=bool_env("HEADLESS", default=False),
            slow_mo=60,
        )
        page = browser.new_page()

        login(page, log)
        abrir_cadastro_base(page, log)
        pesquisar_chope(page, produto, log)
        selecionar_produto(page, log)
        abrir_modal_liberacao(page, log)

        ativados = selecionar_locais_exatos(page, unidades, log)

        salvar(page, dry_run, log)
        time.sleep(2)
        browser.close()

    return {
        "produto": produto,
        "unidades_ativadas": len(ativados),
        "unidades": ativados,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Libera chope novo no Dashboard ZigPay.")
    parser.add_argument("produto", help="Nome do chope para pesquisar")
    parser.add_argument("--unidade", action="append", default=[], help="Unidade para ativar")
    parser.add_argument("--commit", action="store_true", help="Clica em Salvar")
    args = parser.parse_args()

    result = run_liberar_chope_dashboard(
        args.produto,
        args.unidade,
        dry_run=not args.commit,
    )
    print(result)


if __name__ == "__main__":
    main()
