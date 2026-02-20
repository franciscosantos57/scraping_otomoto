import time
import requests
import json
import re
import urllib.parse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from fake_useragent import UserAgent

from models.car import Car, CarSearchParams
from utils.config import (
    OTOMOTO_SEARCH_URL, DEFAULT_HEADERS, 
    FUEL_TYPE_MAP, TRANSMISSION_MAP, HEADLESS_BROWSER
)
from utils.logging_config import get_logger

class OtomotoScraper:
    def __init__(self, use_selenium=True):
        self.logger = get_logger(__name__)
        self.use_selenium = use_selenium
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.ua = UserAgent()
        self.driver = None
        if self.use_selenium:
            self._setup_selenium()

    def _setup_selenium(self):
        options = Options()
        if HEADLESS_BROWSER:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--user-agent={self.ua.random}")
        options.page_load_strategy = 'eager'
        
        self.driver = webdriver.Chrome(options=options)

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
            self.driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(0.5)
        except:
            pass

    def search_cars(self, params: CarSearchParams, max_pages: int = 1):
        all_cars = []

        for page in range(1, max_pages + 1):
            url = self._build_url(params, page=page)
            self.logger.info(f"Pesquisando página {page}: {url}")

            page_cars = []

            # 1. Requests
            try:
                response = self.session.get(url, headers={'User-Agent': self.ua.random})
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    page_cars = self._extract_next_data(soup)
                    if not page_cars:
                        self.logger.info("JSON Vazio no requests, tentando HTML...")
                        page_cars = self._extract_from_html(soup)
            except Exception as e:
                self.logger.error(f"Erro requests (página {page}): {e}")

            # 2. Selenium Fallback
            if not page_cars and self.use_selenium:
                self.logger.info(f"Usando Selenium para página {page}...")
                try:
                    self.driver.get(url)
                    self._scroll_page()
                    try:
                        WebDriverWait(self.driver, 4).until(
                            EC.presence_of_element_located((By.TAG_NAME, "article"))
                        )
                    except: pass

                    soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                    page_cars = self._extract_next_data(soup)
                    if not page_cars:
                        page_cars = self._extract_from_html(soup)
                except Exception as e:
                    self.logger.error(f"Erro Selenium (página {page}): {e}")

            if not page_cars:
                # Sem resultados nesta página → não há mais páginas
                break

            all_cars.extend(page_cars)

            # Se a página trouxe poucos resultados é provável que seja a última
            if len(page_cars) < 10:
                break

        return self._deduplicate(all_cars)

    def _deduplicate(self, cars):
        unique = {}
        for c in cars:
            # Chave única: URL ou Título+Preço+Km
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
                    # Se tiver 'edges', entra neles
                    if 'edges' in obj and isinstance(obj['edges'], list):
                        for edge in obj['edges']:
                            if isinstance(edge, dict) and 'node' in edge:
                                yield edge['node']
                    # Se tiver 'list' (outra estrutura possível)
                    elif 'list' in obj and isinstance(obj['list'], list):
                        for item in obj['list']:
                            yield item
                    # Recurso geral
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
            
            if cars: self.logger.info(f"Extraídos {len(cars)} via JSON (__NEXT_DATA__).")
        except Exception as e:
            self.logger.debug(f"JSON extract erro: {e}")
        
        return cars

    def _parse_node_data(self, node):
        try:
            title = node.get('title')
            url = node.get('url')
            
            # Preço
            price_obj = node.get('price', {})
            # Suporta estruturas variadas de preço
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
        self.logger.info(f"Analisando {len(articles)} artigos HTML...")
        
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
                # Regex flexível: permite espaços, pontos e até pipes opcionais entre numero e moeda
                # Ex: 100 000 PLN, 100.000 zł, 100 000 | PLN
                price_match = re.search(r'(\d[\d\s\.]*)\s*[:\|-]?\s*(PLN|EUR|zł)', text, re.IGNORECASE)
                
                if not price_match: continue
                
                price_str = price_match.group(1).replace(' ', '').replace('.', '').replace(',', '.')
                # Cleanup de ano colado (ex: 201599000)
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

                # 4. Quilometragem (Corrigido: 'km' minúsculo estrito)
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
                # self.logger.debug(f"Erro ao parsear artigo individual: {e}")
                continue
                
        return cars

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            self.driver.quit()