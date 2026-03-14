import os
import csv
import time
import shutil
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from scraper.otomoto_scraper import OtomotoScraper
from models.car import CarSearchParams
from utils.brand_model_validator import validator
from utils.logging_config import get_logger
from utils.config import (
    FULL_EXTRACTION_OUTPUT_DIR, FULL_EXTRACTION_DELAY,
    FULL_EXTRACTION_MAX_PAGES, FULL_EXTRACTION_WORKERS,
)

CSV_FIELDS = ['Título', 'Preço', 'Preço Numérico', 'Moeda', 'Ano', 'Quilometragem', 'Combustível', 'URL']

def _sanitize(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, '-')
    return name.strip().strip('.')

def _save_to_csv(cars: list, path: str) -> None:
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
    logger = get_logger(__name__)
    if os.path.exists(FULL_EXTRACTION_OUTPUT_DIR):
        logger.info(f"A apagar dados antigos na pasta '{FULL_EXTRACTION_OUTPUT_DIR}'...")
        shutil.rmtree(FULL_EXTRACTION_OUTPUT_DIR)
    os.makedirs(FULL_EXTRACTION_OUTPUT_DIR, exist_ok=True)
    logger.info("Pasta de output limpa e pronta.")

_thread_local = threading.local()
_scrapers_lock = threading.Lock()
_all_scrapers: list[OtomotoScraper] = []

def _get_thread_scraper() -> OtomotoScraper:
    if not getattr(_thread_local, 'scraper', None):
        scraper = OtomotoScraper()
        _thread_local.scraper = scraper
        with _scrapers_lock:
            _all_scrapers.append(scraper)
    return _thread_local.scraper

def _close_all_scrapers():
    with _scrapers_lock:
        for s in _all_scrapers:
            try:
                s.close()
            except Exception:
                pass
        _all_scrapers.clear()

def _process_model(task: dict, stats: dict, stats_lock: threading.Lock,
                   total_models: int, start_time: float) -> None:
    logger = get_logger(__name__)

    brand_value  = task['brand_value']
    model_value  = task['model_value']
    model_dir    = task['model_dir']
    csv_path     = task['csv_path']

    try:
        scraper = _get_thread_scraper()
        params  = CarSearchParams(marca=brand_value, modelo=model_value)
        # O scraper agora repete até ter sucesso, garantindo fiabilidade
        results = scraper.search_cars(params, max_pages=FULL_EXTRACTION_MAX_PAGES)

        with stats_lock:
            stats['processed'] += 1
            processed = stats['processed']
            if results:
                stats['with_results'] += 1
                stats['total_cars'] += len(results)
            else:
                stats['empty'] += 1

        elapsed    = time.time() - start_time
        avg_secs   = elapsed / processed if processed > 0 else 0
        eta_secs   = avg_secs * max(total_models - processed, 0)
        eta_str    = str(timedelta(seconds=int(eta_secs)))
        pct        = (processed / total_models) * 100

        if results:
            os.makedirs(model_dir, exist_ok=True)
            _save_to_csv(results, csv_path)
            logger.info(f"[{processed}/{total_models} | {pct:.1f}%] ✓ {brand_value}/{model_value} ({len(results)} carros) | ETA: {eta_str}")
            time.sleep(random.uniform(FULL_EXTRACTION_DELAY[0], FULL_EXTRACTION_DELAY[1]))
        else:
            logger.info(f"[{processed}/{total_models} | {pct:.1f}%] - {brand_value}/{model_value} (Vazio) | ETA: {eta_str}")

    except Exception as e:
        with stats_lock:
            stats['errors']    += 1
            stats['processed'] += 1
            processed = stats['processed']
        logger.error(f"[{processed}/{total_models}] ✗ ERRO em {brand_value}/{model_value}: {e}")

def run_full_extraction() -> dict:
    logger = get_logger(__name__)
    brands = validator.brands

    total_brands = len(brands)
    total_models = sum(len(b.get('models', [])) for b in brands.values())

    logger.info("=" * 60)
    logger.info("EXTRAÇÃO COMPLETA INICIADA (MODO TANQUE)")
    logger.info(f"Marcas:          {total_brands}")
    logger.info(f"Modelos totais:  {total_models}")
    logger.info(f"Workers:         {FULL_EXTRACTION_WORKERS}")
    logger.info(f"Output:          {os.path.abspath(FULL_EXTRACTION_OUTPUT_DIR)}")
    logger.info("=" * 60)

    tasks = []
    for brand_key, brand_data in brands.items():
        brand_value = brand_data['brand_value']
        brand_dir   = os.path.join(FULL_EXTRACTION_OUTPUT_DIR, _sanitize(brand_value))
        for model in brand_data.get('models', []):
            model_value = model['value']
            model_dir   = os.path.join(brand_dir, _sanitize(model_value))
            tasks.append({
                'brand_value': brand_value,
                'model_value': model_value,
                'model_dir':   model_dir,
                'csv_path':    os.path.join(model_dir, f"{_sanitize(model_value)}.csv"),
            })

    stats      = {'processed': 0, 'with_results': 0, 'empty': 0, 'errors': 0, 'total_cars': 0}
    stats_lock = threading.Lock()
    start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=FULL_EXTRACTION_WORKERS) as executor:
            futures = [
                executor.submit(_process_model, task, stats, stats_lock, total_models, start_time)
                for task in tasks
            ]
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    logger.error(f"Erro inesperado no worker: {exc}")
    finally:
        _close_all_scrapers()

    _print_summary(logger, stats, total_models, start_time)
    return stats

def _print_summary(logger, stats: dict, total_models: int, start_time: float) -> None:
    elapsed_secs = int(time.time() - start_time)
    elapsed_str  = str(timedelta(seconds=elapsed_secs))

    logger.info("=" * 60)
    logger.info("EXTRAÇÃO COMPLETA — RESUMO FINAL")
    logger.info(f"  Total modelos na BD:    {total_models}")
    logger.info(f"  Processados:            {stats['processed']}")
    logger.info(f"    Com resultados:       {stats['with_results']}")
    logger.info(f"    Sem resultados:       {stats['empty']}")
    logger.info(f"  Total de Carros Extraídos: {stats['total_cars']}")
    logger.info(f"  Erros de extração:      {stats['errors']}")
    logger.info(f"  Tempo total decorrido:  {elapsed_str}")
    logger.info("=" * 60)