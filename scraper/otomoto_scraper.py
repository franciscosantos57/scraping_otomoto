import time
import json
import re
import urllib.parse
import random
import threading
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

from models.car import Car, CarSearchParams
from utils.config import (
    OTOMOTO_SEARCH_URL,
    FUEL_TYPE_MAP, TRANSMISSION_MAP, HEADLESS_BROWSER,
    USE_PROXIES, PROXIES
)
from utils.logging_config import get_logger

_BLOCK_TITLE_SIGNALS = [
    "just a moment", "attention required", "access denied",
    "403 forbidden", "429 too many requests", "service unavailable",
]
_BLOCK_BODY_SIGNALS = [
    "are you a robot", "i'm not a robot", "solve the captcha",
    "cf-browser-verification", "checking your browser before accessing",
    "verifying you are human", "sorry, you have been blocked",
    "enable javascript and cookies to continue", "ray id:",
    "pardon our interruption", "your access to this site has been limited",
]

# Gestão de proxies em tempo real (Thread-safe)
_proxy_lock = threading.Lock()
ACTIVE_PROXIES = PROXIES.copy() if USE_PROXIES else []

class OtomotoScraper:
    def __init__(self):
        self.logger = get_logger(__name__)
        self.ua = UserAgent(browsers=['chrome', 'edge'], os=['windows', 'macos'])
        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.current_proxy = None
        self._setup_playwright()

    def _get_random_proxy(self):
        global ACTIVE_PROXIES
        if not USE_PROXIES or not PROXIES:
            return None
        with _proxy_lock:
            # Se as proxies forem todas bloqueadas, reinicia a lista
            if not ACTIVE_PROXIES:
                self.logger.warning("A reciclar a lista de proxies (todas foram banidas temporariamente)...")
                ACTIVE_PROXIES = PROXIES.copy()
            return random.choice(ACTIVE_PROXIES)

    def _burn_current_proxy(self):
        global ACTIVE_PROXIES
        if self.current_proxy:
            with _proxy_lock:
                if self.current_proxy in ACTIVE_PROXIES:
                    ip = urllib.parse.urlparse(self.current_proxy).hostname
                    self.logger.warning(f"A queimar proxy {ip} devido a bloqueio ou timeout.")
                    ACTIVE_PROXIES.remove(self.current_proxy)

    def _setup_playwright(self):
        try:
            self._playwright = sync_playwright().start()
            self.current_proxy = self._get_random_proxy()
            
            proxy_settings = None
            if self.current_proxy:
                parsed = urllib.parse.urlparse(self.current_proxy)
                proxy_settings = {
                    "server":   f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                    "username": parsed.username or "",
                    "password": parsed.password or "",
                }

            self.browser = self._playwright.chromium.launch(
                headless=HEADLESS_BROWSER,
                proxy=proxy_settings,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security"
                ]
            )

            self.context = self.browser.new_context(
                user_agent=self.ua.random,
                viewport={"width": random.randint(1280, 1920), "height": random.randint(720, 1080)},
                locale="pl-PL", timezone_id="Europe/Warsaw"
            )
            self.page = self.context.new_page()

            # MODO ULTRA-POUPANÇA (Poupa GBs)
            def intercept_route(route):
                resource_type = route.request.resource_type
                url = route.request.url.lower()
                
                # Bloquear ficheiros desnecessários para extração de dados.
                # NOTA: "script" bloqueia apenas ficheiros .js externos (não inline scripts como __NEXT_DATA__).
                # Bundles Next.js (~2-4MB) eram re-descarregados em cada proxy rotation → principal fonte de bandwidth.
                if resource_type in ["image", "media", "font", "stylesheet", "script"]:
                    return route.abort()
                    
                blocked_domains = ['google', 'criteo', 'gemius', 'hotjar', 'facebook', 'tiktok', 'adsystem', 'doubleclick']
                if any(domain in url for domain in blocked_domains):
                    return route.abort()
                    
                route.continue_()

            self.page.route("**/*", intercept_route)
            Stealth().use_sync(self.page)
            self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
        except Exception as e:
            self.logger.error(f"Erro no Setup Playwright: {e}")

    def _restart_playwright(self, burn_proxy=False):
        if burn_proxy:
            self._burn_current_proxy()
        self.close()
        self._setup_playwright()

    def _is_blocked(self, html: str, status: int | None = None) -> bool:
        lower = html.lower()
        if '__next_data__' in lower or '<article' in lower: return False
        if status and status in (403, 429, 503, 400): return True
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if title_match and any(s in title_match.group(1).lower() for s in _BLOCK_TITLE_SIGNALS): return True
        if any(s in lower for s in _BLOCK_BODY_SIGNALS): return True
        return False

    def _build_url(self, params: CarSearchParams, page: int = 1) -> str:
        query_params = {'search[advanced_search_expanded]': 'true'}
        if page > 1: query_params['page'] = page
        if params.marca: query_params['search[filter_enum_make]'] = params.marca
        if params.modelo: query_params['search[filter_enum_model]'] = params.modelo
        return f"{OTOMOTO_SEARCH_URL}?{urllib.parse.urlencode(query_params)}"

    def search_cars(self, params: CarSearchParams, max_pages: int = None):
        all_cars = []
        page = 1

        while True:
            if max_pages and page > max_pages: break

            url = self._build_url(params, page=page)
            html, http_status = None, None
            page_cars = []

            # MODO TANQUE: Loop infinito. Se a proxy falhar, tenta com outra até sacar a página!
            success = False
            while not success:
                try:
                    response_obj = self.page.goto(url, wait_until="domcontentloaded", timeout=35_000)
                    http_status = response_obj.status if response_obj else None
                    
                    try: self.page.wait_for_selector("article", timeout=2_500)
                    except PlaywrightTimeout: pass
                    
                    html = self.page.content()

                    if self._is_blocked(html, http_status):
                        self.logger.warning(f"Cloudflare Block (HTTP {http_status}). A trocar proxy e repetir...")
                        self._restart_playwright(burn_proxy=True)
                        time.sleep(1)
                        continue 

                    success = True 

                except PlaywrightTimeout:
                    self.logger.warning("⏳ Timeout/Proxy lenta. A trocar proxy e repetir...")
                    self._restart_playwright(burn_proxy=True)
                except Exception as e:
                    self.logger.warning(f"Erro de ligação. A trocar proxy e repetir... ({str(e)[:50]})")
                    self._restart_playwright(burn_proxy=True)

            # --- Extração de Dados ---
            # Extração directa via regex no HTML raw: evita construir DOM completo para o caminho feliz.
            # BeautifulSoup apenas é instanciado como fallback (muito mais raro).
            page_cars = self._extract_next_data_raw(html)
            if not page_cars:
                soup = BeautifulSoup(html, 'lxml')
                page_cars = self._extract_from_html(soup)

            if not page_cars:
                break

            all_cars.extend(page_cars)
            
            if len(page_cars) < 10:
                break

            page += 1
            time.sleep(random.uniform(0.1, 0.3))

        return self._deduplicate(all_cars)

    def _extract_next_data_raw(self, html: str) -> list:
        """Extrai __NEXT_DATA__ directamente do HTML raw via regex, sem construir DOM.
        
        O <script id="__NEXT_DATA__"> é um inline script (SSR do Next.js) — não é um
        ficheiro externo, por isso não é afectado pelo bloqueio de resource_type 'script'.
        """
        cars = []
        try:
            match = re.search(
                r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
                html, re.DOTALL
            )
            if not match:
                return []
            data = json.loads(match.group(1))

            def find_items(obj):
                if isinstance(obj, dict):
                    if 'edges' in obj and isinstance(obj['edges'], list):
                        for edge in obj['edges']:
                            if isinstance(edge, dict) and 'node' in edge: yield edge['node']
                    elif 'list' in obj and isinstance(obj['list'], list):
                        for item in obj['list']: yield item
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)): yield from find_items(v)
                elif isinstance(obj, list):
                    for item in obj: yield from find_items(item)

            for item in find_items(data):
                if isinstance(item, dict):
                    if 'title' in item and 'price' in item and ('url' in item or 'id' in item):
                        car = self._parse_node_data(item)
                        if car: cars.append(car)
        except Exception:
            pass
        return cars

    def _deduplicate(self, cars):
        unique = {}
        for c in cars:
            key = c.url if c.url else f"{c.titulo}_{c.preco}_{c.quilometragem}"
            unique[key] = c
        return list(unique.values())

    def _parse_node_data(self, node):
        try:
            title = node.get('title')
            url = node.get('url')
            price_obj = node.get('price', {})
            if 'amount' in price_obj and isinstance(price_obj['amount'], dict):
                amount = price_obj['amount'].get('units')
                currency = price_obj['amount'].get('currencyCode', 'PLN')
            elif isinstance(price_obj, (int, float, str)):
                 amount = price_obj
                 currency = node.get('currency', 'PLN')
            else: return None
            if not amount: return None
            price_val = float(amount)
            year, mileage, fuel = None, None, None
            for p in node.get('parameters', []):
                key = p.get('key')
                val = p.get('displayValue') or p.get('value')
                if key == 'year': year = int(val) if val else None
                elif key == 'mileage': mileage = str(val) + " km" if val else None
                elif key == 'fuel_type': fuel = val
            return Car(titulo=title, preco=f"{price_val:.0f} {currency}", preco_numerico=price_val, moeda=currency, ano=year, quilometragem=mileage, combustivel=fuel, url=url)
        except: return None

    def _extract_from_html(self, soup):
        cars = []
        articles = soup.find_all('article')
        for article in articles:
            try:
                link = article.find('a', href=True)
                if not link: continue
                url = link['href']
                title_tag = article.select_one('h1, h2, h3')
                title = title_tag.get_text().strip() if title_tag else "N/A"
                text = article.get_text(" ")
                price_match = re.search(r'(\d[\d\s\.]*)\s*[:\|-]?\s*(PLN|EUR|zł)', text, re.IGNORECASE)
                if not price_match: continue
                price_str = price_match.group(1).replace(' ', '').replace('.', '').replace(',', '.')
                if len(price_str) > 7 and price_str.startswith("20"): price_str = price_str[4:]
                try: price_val = float(price_str)
                except: continue
                if price_val < 500: continue
                currency = price_match.group(2).upper()
                if 'ZŁ' in currency: currency = 'PLN'
                year = None
                year_match = re.search(r'\b(19\d{2}|20[0-3]\d)\b', text)
                if year_match: year = int(year_match.group(1))
                mileage = None
                km_match = re.search(r'(\d[\d\s\.]*)\s*km\b', text) 
                if km_match: mileage = f"{km_match.group(1).strip()} km"
                fuel = None
                polish_fuels = {'Benzyna': 'Benzyna', 'Diesel': 'Diesel', 'Hybryda': 'Hybryda', 'Elektryczny': 'Elektryczny', 'LPG': 'LPG'}
                for pl_name, val in polish_fuels.items():
                    if pl_name.lower() in text.lower():
                        fuel = val
                        break
                cars.append(Car(titulo=title, preco=f"{price_val:.0f} {currency}", preco_numerico=price_val, moeda=currency, ano=year, quilometragem=mileage, combustivel=fuel, url=url))
            except Exception: continue
        return cars

    def close(self):
        for attr, method in [('page', 'close'), ('context', 'close'), ('browser', 'close'), ('_playwright', 'stop')]:
            obj = getattr(self, attr, None)
            if obj:
                try: getattr(obj, method)()
                except Exception: pass
        self.page = self.context = self.browser = self._playwright = None

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): self.close()