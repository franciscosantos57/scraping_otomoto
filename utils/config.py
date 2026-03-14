"""
Configurações do projeto Otomoto Scraper
"""
import os

# URLs base
OTOMOTO_BASE_URL = "https://www.otomoto.pl"
OTOMOTO_SEARCH_URL = f"{OTOMOTO_BASE_URL}/osobowe"

# Headers para requests
DEFAULT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# Configurações de scraping
SELENIUM_TIMEOUT = 30
HEADLESS_BROWSER = True  # Mantemos True para não abrires 8 janelas no ecrã ao mesmo tempo

# Mapeamento de Combustível
FUEL_TYPE_MAP = {
    'gasolina': 'petrol', 'gasoleo': 'diesel', 'diesel': 'diesel',
    'gpl': 'lpg', 'hibrido': 'hybrid', 'eletrico': 'electric', 'hidrogenio': 'hydrogen'
}

# Mapeamento de Caixa
TRANSMISSION_MAP = {
    'manual': 'manual', 'automatica': 'automatic'
}

# Localização do ficheiro de base de dados
DATABASE_PATH = os.path.join('data', 'otomoto_database.json')

# Configurações de Extração Completa
FULL_EXTRACTION_OUTPUT_DIR = os.path.join('cars')
FULL_EXTRACTION_DELAY = (0.2, 0.6)
FULL_EXTRACTION_MAX_PAGES = None

# NÚMERO DE THREADS - 8 é o "sweet spot" para RAM/CPU num PC normal com Playwright
FULL_EXTRACTION_WORKERS = 8

# Configurações de Proxies
USE_PROXIES = True
PROXIES = [
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.18:7741",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.69:7793",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.32:7755",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.34:7757",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.200:7924",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.158:7881",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.246:7970",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.189:7912",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.179:7902",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.155:7878",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.114:7838",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.206:7930",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.200:7923",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.21:7744",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.175:7899",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.216:7939",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.62:7785",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.127:7851",
    "http://dsdunkrv:8d0o0toy7n37@82.29.47.207:7931",
    "http://dsdunkrv:8d0o0toy7n37@82.24.35.215:7938"
]