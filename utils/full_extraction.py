"""
Extração Completa do Otomoto
Faz scraping de todas as marcas e modelos presentes na base de dados,
guardando os resultados em CSV por pasta de marca/modelo.

Estrutura de output:
    cars/
        <marca>/
            <modelo>/
                <modelo>.csv
"""

import os
import csv
import time
from datetime import timedelta

from scraper.otomoto_scraper import OtomotoScraper
from models.car import CarSearchParams
from utils.brand_model_validator import validator
from utils.logging_config import get_logger
from utils.config import FULL_EXTRACTION_OUTPUT_DIR, FULL_EXTRACTION_DELAY, FULL_EXTRACTION_MAX_PAGES

CSV_FIELDS = ['Título', 'Preço', 'Preço Numérico', 'Moeda', 'Ano', 'Quilometragem', 'Combustível', 'URL']

def _sanitize(name: str) -> str:
    """Remove caracteres inválidos para nomes de pasta/ficheiro."""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, '-')
    return name.strip().strip('.')

def _save_to_csv(cars: list, path: str) -> None:
    """Guarda lista de Car num ficheiro CSV."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for car in cars:
            writer.writerow({
                'Título':           car.titulo,
                'Preço':            car.preco,
                'Preço Numérico':   car.preco_numerico,
                'Moeda':            car.moeda,
                'Ano':              car.ano,
                'Quilometragem':    car.quilometragem,
                'Combustível':      car.combustivel,
                'URL':              car.url,
            })

def _clear_output_directory():
    """Apaga os dados antigos para garantir uma extração 100% fresca."""
    logger = get_logger(__name__)
    if os.path.exists(FULL_EXTRACTION_OUTPUT_DIR):
        logger.info(f"A apagar dados antigos na pasta '{FULL_EXTRACTION_OUTPUT_DIR}'...")
        shutil.rmtree(FULL_EXTRACTION_OUTPUT_DIR)
    os.makedirs(FULL_EXTRACTION_OUTPUT_DIR, exist_ok=True)
    logger.info("Pasta de output limpa e pronta.")

def run_full_extraction() -> dict:
    """
    Ponto de entrada principal para extração completa.
    Itera sequencialmente por todas as marcas e modelos da base de dados,
    faz scraping de cada combinação e guarda os resultados em CSV.

    Retorna um dicionário com estatísticas da extração.
    """
    logger = get_logger(__name__)
    brands = validator.brands

    total_brands = len(brands)
    total_models = sum(len(b.get('models', [])) for b in brands.values())

    logger.info("=" * 60)
    logger.info("EXTRAÇÃO COMPLETA INICIADA")
    logger.info(f"Marcas:          {total_brands}")
    logger.info(f"Modelos totais:  {total_models}")
    logger.info(f"Páginas/modelo:  {FULL_EXTRACTION_MAX_PAGES if FULL_EXTRACTION_MAX_PAGES else 'ilimitado'}")
    logger.info(f"Delay:           {FULL_EXTRACTION_DELAY}s")
    logger.info(f"Output:          {os.path.abspath(FULL_EXTRACTION_OUTPUT_DIR)}")
    logger.info("=" * 60)

    stats = {'processed': 0, 'with_results': 0, 'empty': 0, 'errors': 0, 'total_cars': 0}
    start_time = time.time()
    model_global_idx = 0

    with OtomotoScraper() as scraper:
        for brand_key, brand_data in brands.items():
            brand_value = brand_data['brand_value']
            brand_text = brand_data.get('text', brand_value)
            brand_dir = os.path.join(FULL_EXTRACTION_OUTPUT_DIR, _sanitize(brand_value))

            models = brand_data.get('models', [])
            for model in models:
                model_global_idx += 1
                model_value = model['value']
                model_text = model.get('text', model_value)
                model_dir = os.path.join(brand_dir, _sanitize(model_value))
                csv_path = os.path.join(model_dir, f"{_sanitize(model_value)}.csv")

                try:
                    params = CarSearchParams(marca=brand_value, modelo=model_value)
                    results = scraper.search_cars(params, max_pages=FULL_EXTRACTION_MAX_PAGES)

                    stats['processed'] += 1
                    elapsed = time.time() - start_time
                    avg_secs = elapsed / stats['processed'] if stats['processed'] > 0 else 0
                    remaining_models = total_models - stats['processed']
                    eta_secs = avg_secs * remaining_models if avg_secs > 0 else 0
                    eta_str = str(timedelta(seconds=int(eta_secs)))
                    pct = (stats['processed'] / total_models) * 100

                    if results:
                        stats['with_results'] += 1
                        stats['total_cars'] += len(results)
                        os.makedirs(model_dir, exist_ok=True)
                        _save_to_csv(results, csv_path)
                        logger.info(f"[{stats['processed']}/{total_models} | {pct:.1f}%] ✓ {brand_value}/{model_value} ({len(results)} carros) | ETA: {eta_str}")
                    else:
                        stats['empty'] += 1
                        logger.info(f"[{stats['processed']}/{total_models} | {pct:.1f}%] - {brand_value}/{model_value} (Vazio) | ETA: {eta_str}")

                    time.sleep(FULL_EXTRACTION_DELAY)

                except Exception as e:
                    stats['errors'] += 1
                    stats['processed'] += 1
                    logger.error(f"[{stats['processed']}/{total_models}] ✗ ERRO em {brand_value}/{model_value}: {e}")

    _print_summary(logger, stats, total_models, start_time)
    return stats


def _print_summary(logger, stats: dict, total_models: int, start_time: float) -> None:
    elapsed_secs = int(time.time() - start_time)
    elapsed_str  = str(timedelta(seconds=elapsed_secs))
    processed    = stats['processed']
    
    logger.info("=" * 60)
    logger.info("EXTRAÇÃO COMPLETA — RESUMO FINAL")
    logger.info(f"  Total modelos na BD:    {total_models}")
    logger.info(f"  Processados:            {processed}")
    logger.info(f"    Com resultados:       {stats['with_results']}")
    logger.info(f"    Sem resultados:       {stats['empty']}")
    logger.info(f"  Total de Carros Extraídos: {stats['total_cars']}")
    logger.info(f"  Erros de extração:      {stats['errors']}")
    logger.info(f"  Tempo total decorrido:  {elapsed_str}")
    logger.info("=" * 60)