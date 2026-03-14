"""
Valida se os `value` de marcas e modelos na base de dados correspondem
a URLs reais do Otomoto.

Estratégia:
  Para cada marca/modelo, abre o URL correspondente e verifica se o Otomoto
  reconhece o slug. Se o slug for inválido, o Otomoto redireciona para uma
  página genérica sem o slug no URL final — isso é o sinal de que está errado.

  URL de marca:  https://www.otomoto.pl/osobowe/{brand_value}/
  URL de modelo: https://www.otomoto.pl/osobowe/{brand_value}/{model_value}/

  Válido   → URL final ainda contém o slug
  Inválido → URL final não tem o slug (redirecionou para outra página)

Uso:
    python3 -m utils.validate_db_values              # valida tudo (8 workers async)
    python3 -m utils.validate_db_values --marca bmw  # só uma marca + modelos dela
    python3 -m utils.validate_db_values --marca bmw --modelo x5  # só um modelo
    python3 -m utils.validate_db_values --so-marcas  # só marcas, sem modelos
    python3 -m utils.validate_db_values --workers 12 # ajustar concorrência
"""

import asyncio
import json
import random
import argparse
import urllib.parse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth
from fake_useragent import UserAgent

from utils.config import OTOMOTO_SEARCH_URL, USE_PROXIES, PROXIES
from utils.brand_model_validator import validator
from utils.logging_config import get_logger, setup_logging

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug_in_url(final_url: str, slug: str) -> bool:
    """Devolve True se o slug ainda está presente no URL final após navegação."""
    return f"/{slug}/" in final_url or final_url.rstrip("/").endswith(f"/{slug}")


def _proxy_settings():
    if not (USE_PROXIES and PROXIES):
        return None
    parsed = urllib.parse.urlparse(random.choice(PROXIES))
    return {
        "server":   f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
        "username": parsed.username or "",
        "password": parsed.password or "",
    }


# ---------------------------------------------------------------------------
# Async core — pool de páginas, sem threads
# ---------------------------------------------------------------------------

async def _check_url_async(page, target_url: str, slug: str, retries: int = 3):
    """
    Navega para target_url e verifica se o slug permanece no URL final.
    Retorna True se válido, False se inválido, None se inconclusivo.
    """
    for attempt in range(retries):
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=35_000)
            final_url = page.url
            await asyncio.sleep(random.uniform(0.05, 0.15))
            return _slug_in_url(final_url, slug)
        except PlaywrightTimeout:
            logger.debug(f"Timeout ({attempt + 1}/{retries}): {target_url}")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"Erro ({attempt + 1}/{retries}) {target_url}: {e}")
            await asyncio.sleep(1.0)
    return None


async def _validate_async(brand_tasks, model_tasks, workers: int):
    ua = UserAgent(browsers=['chrome', 'edge'], os=['windows', 'macos'])
    total_tasks = len(brand_tasks) + len(model_tasks)

    results = {
        "marcas_ok": [], "marcas_nok": [], "marcas_inconcluso": [],
        "modelos_ok": [], "modelos_nok": [], "modelos_inconcluso": [],
    }
    lock = asyncio.Lock()
    counter = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            proxy=_proxy_settings(),
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )

        # Pool de páginas — uma por worker
        pages = []
        for _ in range(workers):
            ctx = await browser.new_context(
                user_agent=ua.random,
                viewport={"width": 1440, "height": 900},
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
            )
            page = await ctx.new_page()
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,mp4,webm}",
                lambda r: r.abort(),
            )
            await Stealth().apply_stealth_async(page)
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            pages.append(page)

        page_queue: asyncio.Queue = asyncio.Queue()
        for p in pages:
            await page_queue.put(p)

        async def run_task(kind, url, slug, extra):
            nonlocal counter
            page = await page_queue.get()
            try:
                ok = await _check_url_async(page, url, slug)
            finally:
                await page_queue.put(page)

            async with lock:
                counter += 1
                n = counter
                pct = n / total_tasks * 100
                if kind == "brand":
                    bv, bt = slug, extra
                    if ok is True:
                        results["marcas_ok"].append((bv, bt))
                        logger.info(f"[{n}/{total_tasks} {pct:.0f}%] ✓ Marca '{bv}'")
                    elif ok is False:
                        results["marcas_nok"].append((bv, bt))
                        logger.warning(f"[{n}/{total_tasks} {pct:.0f}%] ✗ Marca '{bv}' ('{bt}')")
                    else:
                        results["marcas_inconcluso"].append((bv, bt))
                        logger.warning(f"[{n}/{total_tasks} {pct:.0f}%] ? Marca '{bv}' (inconclusivo)")
                else:
                    bv, mv, mt = extra
                    if ok is True:
                        results["modelos_ok"].append((bv, mv, mt))
                        logger.info(f"[{n}/{total_tasks} {pct:.0f}%] ✓ Modelo '{bv}/{mv}'")
                    elif ok is False:
                        results["modelos_nok"].append((bv, mv, mt))
                        logger.warning(f"[{n}/{total_tasks} {pct:.0f}%] ✗ Modelo '{bv}/{mv}' ('{mt}')")
                    else:
                        results["modelos_inconcluso"].append((bv, mv, mt))
                        logger.warning(f"[{n}/{total_tasks} {pct:.0f}%] ? Modelo '{bv}/{mv}' (inconclusivo)")

        coros = []
        for bv, bt in brand_tasks:
            url = f"{OTOMOTO_SEARCH_URL}/{bv}/"
            coros.append(run_task("brand", url, bv, bt))
        for bv, mv, mt in model_tasks:
            url = f"{OTOMOTO_SEARCH_URL}/{bv}/{mv}/"
            coros.append(run_task("model", url, mv, (bv, mv, mt)))

        await asyncio.gather(*coros)

        await browser.close()

    return results


# ---------------------------------------------------------------------------
# Validação principal (entry point síncrono)
# ---------------------------------------------------------------------------

def validate(filter_marca: str = None, filter_modelo: str = None,
             so_marcas: bool = False, workers: int = 8):

    db_brands = validator.brands

    if filter_marca:
        marca_lower = filter_marca.lower()
        db_brands = {k: v for k, v in db_brands.items()
                     if v.get("brand_value", "").lower() == marca_lower
                     or k.lower() == marca_lower}
        if not db_brands:
            print(f"\n[ERRO] Marca '{filter_marca}' não encontrada na BD.")
            return

    brand_tasks = []
    model_tasks = []

    for brand_key, brand_data in db_brands.items():
        bv = brand_data.get("brand_value", "")
        bt = brand_data.get("brand_text", brand_key)
        brand_tasks.append((bv, bt))

        if not so_marcas:
            models = brand_data.get("models", [])
            if filter_modelo:
                models = [m for m in models
                          if m.get("value", "").lower() == filter_modelo.lower()]
            for m in models:
                model_tasks.append((bv, m.get("value", ""), m.get("text", "")))

    total_tasks = len(brand_tasks) + len(model_tasks)
    print(f"\nA validar {len(brand_tasks)} marcas e {len(model_tasks)} modelos "
          f"({total_tasks} requests) com {workers} workers async...\n")

    results = asyncio.run(_validate_async(brand_tasks, model_tasks, workers))

    # ---------------------------------------------------------------------------
    # Relatório
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 65)
    print("RELATÓRIO DE VALIDAÇÃO DA BASE DE DADOS")
    print("=" * 65)

    print(f"\n📌 MARCAS")
    print(f"  Válidas:       {len(results['marcas_ok'])}")
    print(f"  Inválidas:     {len(results['marcas_nok'])}")
    print(f"  Inconclusivas: {len(results['marcas_inconcluso'])}")
    if results["marcas_nok"]:
        print()
        for bv, bt in results["marcas_nok"]:
            print(f"  ✗  value='{bv}'  (texto: '{bt}')")
            print(f"     URL tentada: {OTOMOTO_SEARCH_URL}/{bv}/")

    if not so_marcas:
        print(f"\n📌 MODELOS")
        print(f"  Válidos:       {len(results['modelos_ok'])}")
        print(f"  Inválidos:     {len(results['modelos_nok'])}")
        print(f"  Inconclusivos: {len(results['modelos_inconcluso'])}")
        if results["modelos_nok"]:
            print()
            by_brand: dict = {}
            for bv, mv, mt in results["modelos_nok"]:
                by_brand.setdefault(bv, []).append((mv, mt))
            for brand_v, erros in by_brand.items():
                print(f"  Marca: {brand_v}")
                for mv, mt in erros:
                    print(f"    ✗  value='{mv}'  (texto: '{mt}')")
                    print(f"       URL: {OTOMOTO_SEARCH_URL}/{brand_v}/{mv}/")

    total_nok = len(results["marcas_nok"]) + len(results["modelos_nok"])
    total_inc = len(results["marcas_inconcluso"]) + len(results["modelos_inconcluso"])

    print("\n" + "=" * 65)
    if total_nok == 0 and total_inc == 0:
        print("✅ Tudo correto! Nenhum value errado encontrado.")
    else:
        if total_nok:
            print(f"⚠️  {total_nok} values inválidos encontrados.")
        if total_inc:
            print(f"❓  {total_inc} inconclusivos (timeout/rede).")
    print("=" * 65 + "\n")

    if total_nok > 0:
        output = {
            "marcas_invalidas": [{"value": bv, "text": bt}
                                  for bv, bt in results["marcas_nok"]],
            "modelos_invalidos": [{"marca": bv, "value": mv, "text": mt}
                                   for bv, mv, mt in results["modelos_nok"]],
        }
        out_path = "data/validation_errors.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"📄 Erros guardados em: {out_path}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    setup_logging()

    parser = argparse.ArgumentParser(description="Validar values da BD contra o Otomoto")
    parser.add_argument("--marca",     type=str,  default=None, help="Só esta marca (ex: bmw)")
    parser.add_argument("--modelo",    type=str,  default=None, help="Só este modelo (ex: x5)")
    parser.add_argument("--so-marcas", action="store_true",     help="Só marcas, sem modelos")
    parser.add_argument("--workers",   type=int,  default=8,    help="Páginas async simultâneas (default: 8)")
    args = parser.parse_args()

    validate(
        filter_marca=args.marca,
        filter_modelo=args.modelo,
        so_marcas=args.so_marcas,
        workers=args.workers,
    )
