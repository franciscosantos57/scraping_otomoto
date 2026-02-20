"""
Configurações do projeto Otomoto Scraper
"""
import os

# URLs base
OTOMOTO_BASE_URL = "https://www.otomoto.pl"
OTOMOTO_SEARCH_URL = f"{OTOMOTO_BASE_URL}/osobowe"

# Headers para requests
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# Configurações de scraping
DELAY_BETWEEN_REQUESTS = 1.0
SELENIUM_TIMEOUT = 10
HEADLESS_BROWSER = True

# Mapeamento de Combustível (Input -> Parâmetro URL Otomoto)
FUEL_TYPE_MAP = {
    'gasolina': 'petrol',
    'gasoleo': 'diesel',
    'diesel': 'diesel',
    'gpl': 'lpg',
    'hibrido': 'hybrid',
    'eletrico': 'electric',
    'hidrogenio': 'hydrogen'
}

# Mapeamento de Caixa (Input -> Parâmetro URL Otomoto)
TRANSMISSION_MAP = {
    'manual': 'manual',
    'automatica': 'automatic'
}

# Localização do ficheiro de base de dados
DATABASE_PATH = os.path.join('data', 'otomoto_database.json')

# Configurações de Extração Completa
FULL_EXTRACTION_OUTPUT_DIR = os.path.join('cars')    # Pasta raiz de output
FULL_EXTRACTION_DELAY = 2.5                           # Segundos entre requests (respeito ao servidor)
FULL_EXTRACTION_MAX_PAGES = 3                         # Páginas máximas por marca/modelo