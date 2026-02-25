import time
import json
import re
import urllib.parse
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

from models.car import Car, CarSearchParams
from utils.config import (
    OTOMOTO_SEARCH_URL,
    FUEL_TYPE_MAP, TRANSMISSION_MAP, HEADLESS_BROWSER
)
from utils.logging_config import get_logger

# Frases específicas de páginas de challenge/bloqueio (título ou corpo)
# Deliberadamente precisas para evitar falsos positivos no conteúdo normal.
_BLOCK_TITLE_SIGNALS = [
    "just a moment",           # Cloudflare waiting room (título)
    "attention required",      # Cloudflare block (título)
    "access denied",
    "403 forbidden",
    "429 too many requests",
    "service unavailable",
]
_BLOCK_BODY_SIGNALS = [
    "are you a robot",
    "i'm not a robot",
    "solve the captcha",
    "cf-browser-verification",
    "checking your browser before accessing",
    "verifying you are human",
    "sorry, you have been blocked",
    "enable javascript and cookies to continue",
    "ray id:",                  # Cloudflare block page footer
    "pardon our interruption",  # Akamai
    "your access to this site has been limited",  # Sucuri / WordFence
]


class OtomotoScraper:
    def __init__(self):
        self.logger = get_logger(__name__)
        self.ua = UserAgent()
        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._setup_playwright()

    def _setup_playwright(self):
        """Configura o Playwright com modo Stealth para evitar deteção."""
        try:
            self._playwright = sync_playwright().start()
            self.browser = self._playwright.chromium.launch(
                headless=HEADLESS_BROWSER,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            self.context = self.browser.new_context(
                user_agent=self.ua.random,
                viewport={"width": 1366, "height": 768},
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                extra_http_headers={
                    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            )
            self.page = self.context.new_page()

            # Bloquear imagens/fontes para velocidade (sem prejudicar o HTML/JSON)
            self.page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,otf}",
                lambda route: route.abort()
            )

            # Modo stealth: patcha navigator.webdriver, plugins, canvas, etc.
            Stealth().use_sync(self.page)
            self.logger.info("Playwright configurado com modo Stealth.")
        except Exception as e:
            self.logger.error(f"Erro ao configurar Playwright: {e}")

    def _restart_playwright(self):
        """Recria browser + contexto para limpar cookies/estado."""
        self.logger.info("A reiniciar sessão Playwright...")
        try:
            if self.page:    self.page.close()
            if self.context: self.context.close()
            if self.browser: self.browser.close()
            if self._playwright: self._playwright.stop()
        except Exception:
            pass
        self._playwright = self.browser = self.context = self.page = None
        self._setup_playwright()

    def _is_blocked(self, html: str, status: int | None = None) -> bool:
        """
        Devolve True se a página indica que estamos a ser bloqueados.

        Regra de ouro: se a página tiver __NEXT_DATA__ ou <article>,
        o conteúdo esperado está presente → nunca consideramos bloqueio.

        Verifica:
          1. Código HTTP de bloqueio (403, 429, 503)
          2. Sinais no título da página (muito precisos)
          3. Sinais específicos de challenge pages no corpo
          4. Página de conteúdo praticamente vazia (< 500 chars visíveis)
        """
        # Regra de ouro: conteúdo esperado presente → não há bloqueio
        lower = html.lower()
        if '__next_data__' in lower or '<article' in lower:
            return False

        # 1. HTTP status de bloqueio
        if status and status in (403, 429, 503):
            self.logger.warning(f"BLOQUEADO: HTTP {status} recebido.")
            return True

        # 2. Título da página (mais fiável, sem falsos positivos)
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title_text = title_match.group(1).lower() if title_match else ""
        for signal in _BLOCK_TITLE_SIGNALS:
            if signal in title_text:
                self.logger.warning(f"BLOQUEADO: título '{title_text.strip()[:80]}'.")
                return True

        # 3. Frases precisas de bot-challenge no corpo
        for signal in _BLOCK_BODY_SIGNALS:
            if signal in lower:
                self.logger.warning(f"BLOQUEADO: sinal '{signal}' detetado na página.")
                return True

        # 4. Página quase vazia sem qualquer conteúdo relevante
        visible_text_len = len(re.sub(r'<[^>]+>', '', html).replace('\n', '').replace(' ', ''))
        if visible_text_len < 300:
            self.logger.warning("BLOQUEADO: página sem conteúdo (< 300 chars visíveis).")
            return True

        return False

    def _build_url(self, params: CarSearchParams, page: int = 1) -> str:
        query_params = {
            'search[advanced_search_expanded]': 'true'
        }
        if page > 1:
            query_params['page'] = page
        if params.marca: query_params['search[filter_enum_make]'] = params.marca
        if params.modelo: query_params['search[filter_enum_model]'] = params.modelo
        if params.ano_min: query_params['search[filter_float_year:from]'] = params.ano_min
        if params.ano_max: query_params['search[filter_float_year:to]'] = params.ano_max
        if params.km_max: query_params['search[filter_float_mileage:to]'] = params.km_max
        if params.preco_max: query_params['search[filter_float_price:to]'] = params.preco_max
        if params.combustivel and params.combustivel in FUEL_TYPE_MAP:
            query_params['search[filter_enum_fuel_type]'] = FUEL_TYPE_MAP[params.combustivel]
        if params.caixa and params.caixa in TRANSMISSION_MAP:
            query_params['search[filter_enum_gearbox]'] = TRANSMISSION_MAP[params.caixa]

        query_string = urllib.parse.urlencode(query_params)
        return f"{OTOMOTO_SEARCH_URL}?{query_string}"

    def _scroll_page(self):
        try:
            if self.page:
                self.page.evaluate("window.scrollBy(0, 600)")
                time.sleep(0.3)
        except Exception:
            pass

    def search_cars(self, params: CarSearchParams, max_pages: int = None):
        """
        Pesquisa com Playwright+Stealth como método principal.
        Deteta bloqueios ativamente e aplica back-off exponencial antes de reintentar.
        """
        all_cars = []
        page = 1
        consecutive_errors = 0
        block_retries = 0
        MAX_BLOCK_RETRIES = 3
        BLOCK_BACKOFF = [15, 45, 120]  # segundos de espera a cada bloqueio consecutivo

        while True:
            if max_pages and page > max_pages:
                self.logger.info(f"Limite máximo de {max_pages} páginas atingido.")
                break

            # === WATCHDOG: reinício preventivo a cada 50 páginas ===
            if self.browser and page > 1 and page % 50 == 0:
                self.logger.info(f"Manutenção: Reinício preventivo na página {page}...")
                self._restart_playwright()
                time.sleep(2)

            url = self._build_url(params, page=page)
            self.logger.info(f"Pesquisando página {page}: {url}")

            page_cars = []
            html = None
            http_status = None

            # === PLAYWRIGHT (único método) ===
            try:
                response_obj = self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                http_status = response_obj.status if response_obj else None
                self._scroll_page()

                try:
                    self.page.wait_for_selector("article", timeout=5_000)
                except PlaywrightTimeout:
                    pass  # pode ser página legítima sem artigos

                html = self.page.content()
            except PlaywrightTimeout:
                self.logger.warning(f"Timeout ao carregar página {page}.")
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    self.logger.error("3 timeouts consecutivos. Parando busca.")
                    break
                self._restart_playwright()
                time.sleep(5)
                continue
            except Exception as e:
                self.logger.warning(f"Erro Playwright (página {page}): {e}")
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    self.logger.error("Muitas falhas consecutivas. Parando busca.")
                    break
                self._restart_playwright()
                time.sleep(5)
                continue

            # === DETEÇÃO DE BLOQUEIO ===
            if self._is_blocked(html, http_status):
                block_retries += 1
                if block_retries > MAX_BLOCK_RETRIES:
                    self.logger.error(
                        f"BLOQUEADO {block_retries}x consecutivas. "
                        "A abandonar este modelo."
                    )
                    break

                wait_secs = BLOCK_BACKOFF[min(block_retries - 1, len(BLOCK_BACKOFF) - 1)]
                self.logger.warning(
                    f"Bloqueio detetado (tentativa {block_retries}/{MAX_BLOCK_RETRIES}). "
                    f"A aguardar {wait_secs}s e a reiniciar browser..."
                )
                self._restart_playwright()
                time.sleep(wait_secs)
                continue  # re-tenta a mesma página

            # Página carregada sem bloqueio — reset dos contadores
            consecutive_errors = 0
            block_retries = 0

            # === EXTRAÇÃO ===
            soup = BeautifulSoup(html, 'html.parser')
            page_cars = self._extract_next_data(soup)
            if not page_cars:
                page_cars = self._extract_from_html(soup)

            if not page_cars:
                self.logger.info(f"Nenhum carro encontrado na página {page}. Fim dos resultados.")
                break

            all_cars.extend(page_cars)
            self.logger.info(
                f"Página {page}: {len(page_cars)} carros encontrados "
                f"(total parcial: {len(all_cars)})"
            )

            if len(page_cars) < 10:
                self.logger.info(
                    f"Página {page} tem poucos resultados ({len(page_cars)}), "
                    "assumindo fim."
                )
                break

            page += 1
            time.sleep(0.5)

        return self._deduplicate(all_cars)

    def _deduplicate(self, cars):
        unique = {}
        for c in cars:
            # Chave única: URL ou Título+Preço+Km se a URL não existir
            key = c.url if c.url else f"{c.titulo}_{c.preco}_{c.quilometragem}"
            unique[key] = c
        return list(unique.values())

    def _extract_next_data(self, soup):
        """Extrai dados do JSON __NEXT_DATA__ do Otomoto"""
        cars = []
        try:
            script = soup.find('script', id='__NEXT_DATA__')
            if not script: return []

            data = json.loads(script.string)
            
            # Navegador recursivo de JSON
            def find_items(obj):
                if isinstance(obj, dict):
                    if 'edges' in obj and isinstance(obj['edges'], list):
                        for edge in obj['edges']:
                            if isinstance(edge, dict) and 'node' in edge:
                                yield edge['node']
                    elif 'list' in obj and isinstance(obj['list'], list):
                        for item in obj['list']:
                            yield item
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)):
                            yield from find_items(v)
                elif isinstance(obj, list):
                    for item in obj:
                        yield from find_items(item)

            for item in find_items(data):
                if isinstance(item, dict):
                    # Validação mínima para ser um carro
                    if 'title' in item and 'price' in item and ('url' in item or 'id' in item):
                         car = self._parse_node_data(item)
                         if car: cars.append(car)
            
            if cars: self.logger.debug(f"Extraídos {len(cars)} via JSON (__NEXT_DATA__).")
        except Exception as e:
            self.logger.debug(f"JSON extract erro: {e}")
        
        return cars

    def _parse_node_data(self, node):
        try:
            title = node.get('title')
            url = node.get('url')
            
            # Preço
            price_obj = node.get('price', {})
            if 'amount' in price_obj and isinstance(price_obj['amount'], dict):
                amount = price_obj['amount'].get('units')
                currency = price_obj['amount'].get('currencyCode', 'PLN')
            elif isinstance(price_obj, (int, float, str)):
                 amount = price_obj
                 currency = node.get('currency', 'PLN')
            else:
                return None

            if not amount: return None
            price_val = float(amount)
            
            # Parâmetros
            year = None
            mileage = None
            fuel = None
            
            params = node.get('parameters', [])
            for p in params:
                key = p.get('key')
                val = p.get('displayValue') or p.get('value')
                
                if key == 'year': 
                    year = int(val) if val else None
                elif key == 'mileage': 
                    mileage = str(val) + " km" if val else None
                elif key == 'fuel_type': 
                    fuel = val

            return Car(
                titulo=title,
                preco=f"{price_val:.0f} {currency}",
                preco_numerico=price_val,
                moeda=currency,
                ano=year,
                quilometragem=mileage,
                combustivel=fuel,
                url=url
            )
        except:
            return None

    def _extract_from_html(self, soup):
        """Extração Visual HTML (Fallback)"""
        cars = []
        articles = soup.find_all('article')
        self.logger.debug(f"Analisando {len(articles)} artigos HTML...")
        
        for article in articles:
            try:
                # 1. URL e Título
                link = article.find('a', href=True)
                if not link: continue
                url = link['href']
                
                title_tag = article.select_one('h1, h2, h3')
                title = title_tag.get_text().strip() if title_tag else "N/A"

                # Texto completo: USAR ESPAÇO COMO SEPARADOR
                text = article.get_text(" ")

                # 2. Preço
                price_match = re.search(r'(\d[\d\s\.]*)\s*[:\|-]?\s*(PLN|EUR|zł)', text, re.IGNORECASE)
                
                if not price_match: continue
                
                price_str = price_match.group(1).replace(' ', '').replace('.', '').replace(',', '.')
                if len(price_str) > 7 and price_str.startswith("20"):
                    price_str = price_str[4:]
                
                try:
                    price_val = float(price_str)
                except: continue

                if price_val < 500: continue
                
                currency = price_match.group(2).upper()
                if 'ZŁ' in currency: currency = 'PLN'

                # 3. Ano (1900-2030)
                year = None
                year_match = re.search(r'\b(19\d{2}|20[0-3]\d)\b', text)
                if year_match: year = int(year_match.group(1))

                # 4. Quilometragem
                mileage = None
                km_match = re.search(r'(\d[\d\s\.]*)\s*km\b', text) 
                if km_match:
                    mileage = f"{km_match.group(1).strip()} km"

                # 5. Combustível
                fuel = None
                polish_fuels = {
                    'Benzyna': 'Benzyna',
                    'Diesel': 'Diesel', 
                    'Hybryda': 'Hybryda',
                    'Elektryczny': 'Elektryczny', 
                    'LPG': 'LPG'
                }
                for pl_name, val in polish_fuels.items():
                    if pl_name.lower() in text.lower():
                        fuel = val
                        break

                cars.append(Car(
                    titulo=title,
                    preco=f"{price_val:.0f} {currency}",
                    preco_numerico=price_val,
                    moeda=currency,
                    ano=year,
                    quilometragem=mileage,
                    combustivel=fuel,
                    url=url
                ))
            except Exception as e:
                continue
                
        return cars

    def close(self):
        """Fecha o browser Playwright."""
        for attr, method in [
            ('page',        'close'),
            ('context',     'close'),
            ('browser',     'close'),
            ('_playwright', 'stop'),
        ]:
            obj = getattr(self, attr, None)
            if obj:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
        self.page = self.context = self.browser = self._playwright = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()