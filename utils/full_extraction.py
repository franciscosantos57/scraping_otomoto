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
import json
from datetime import datetime, timedelta

from scraper.otomoto_scraper import OtomotoScraper
from models.car import CarSearchParams
from utils.brand_model_validator import validator
from utils.logging_config import get_logger
from utils.config import (
    FULL_EXTRACTION_OUTPUT_DIR,
    FULL_EXTRACTION_DELAY,
    FULL_EXTRACTION_MAX_PAGES,
)

# Campos CSV por ordem
CSV_FIELDS = ['Título', 'Preço', 'Preço Numérico', 'Moeda', 'Ano', 'Quilometragem', 'Combustível', 'URL']

# Ficheiro de progresso (para retomar extração interrompida)
PROGRESS_FILE = os.path.join(FULL_EXTRACTION_OUTPUT_DIR, '.progress.json')


def _sanitize(name: str) -> str:
    """Remove caracteres inválidos para nomes de pasta/ficheiro em todos os SO."""
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


def _load_progress() -> set:
    """Carrega conjunto de pares (brand_value, model_value) já processados."""
    if not os.path.exists(PROGRESS_FILE):
        return set()
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return set(tuple(entry) for entry in data.get('done', []))
    except Exception:
        return set()


def _save_progress(done: set) -> None:
    """Persiste o progresso actual em disco."""
    os.makedirs(FULL_EXTRACTION_OUTPUT_DIR, exist_ok=True)
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'done': [list(pair) for pair in done]}, f)


def run_full_extraction() -> dict:
    """
    Ponto de entrada principal para extração completa.
    Itera por todas as marcas e modelos da base de dados,
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
    logger.info(f"Páginas/modelo:  {FULL_EXTRACTION_MAX_PAGES}")
    logger.info(f"Delay:           {FULL_EXTRACTION_DELAY}s")
    logger.info(f"Output:          {os.path.abspath(FULL_EXTRACTION_OUTPUT_DIR)}")
    logger.info(f"Início:          {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    already_done = _load_progress()
    stats = {'processed': 0, 'with_results': 0, 'empty': 0, 'skipped': 0, 'errors': 0}
    start_time = time.time()
    model_global_idx = 0  # contador global de modelos para progresso

    with OtomotoScraper() as scraper:
        for brand_idx, (brand_key, brand_data) in enumerate(brands.items(), start=1):
            brand_value = brand_data['brand_value']
            brand_text  = brand_data['brand_text']
            models      = brand_data.get('models', [])

            brand_dir = os.path.join(FULL_EXTRACTION_OUTPUT_DIR, _sanitize(brand_value))

            logger.info(
                f"[Marca {brand_idx}/{total_brands}] {brand_text} "
                f"({len(models)} modelos)"
            )

            for model in models:
                model_global_idx += 1
                model_value = model['value']
                model_text  = model['text']

                pair = (brand_value, model_value)

                # ── Verificar se já foi processado (resume) ──────────────────
                if pair in already_done:
                    stats['skipped'] += 1
                    logger.debug(f"  [skip] {brand_value}/{model_value} (já existente)")
                    continue

                # ── Caminhos de destino ───────────────────────────────────────
                model_dir = os.path.join(brand_dir, _sanitize(model_value))
                csv_path  = os.path.join(model_dir, f"{_sanitize(model_value)}.csv")

                # Fallback de resume baseado no ficheiro CSV (caso .progress.json não exista)
                if os.path.exists(csv_path):
                    already_done.add(pair)
                    stats['skipped'] += 1
                    logger.debug(f"  [skip] {brand_value}/{model_value} (CSV já existe)")
                    continue

                # ── Scraping ──────────────────────────────────────────────────
                progress_pct = (model_global_idx / total_models) * 100
                elapsed = time.time() - start_time
                if stats['processed'] > 0:
                    avg_secs = elapsed / stats['processed']
                    remaining_models = total_models - model_global_idx
                    eta_secs = avg_secs * remaining_models
                    eta_str = str(timedelta(seconds=int(eta_secs)))
                    elapsed_str = str(timedelta(seconds=int(elapsed)))
                else:
                    eta_str = "--:--:--"
                    elapsed_str = str(timedelta(seconds=int(elapsed)))

                logger.info(
                    f"  [{model_global_idx}/{total_models} | {progress_pct:.1f}%] "
                    f"{brand_value}/{model_value} "
                    f"| decorrido {elapsed_str} | ETA {eta_str}"
                )

                try:
                    params  = CarSearchParams(marca=brand_value, modelo=model_value)
                    results = scraper.search_cars(params, max_pages=FULL_EXTRACTION_MAX_PAGES)

                    stats['processed'] += 1

                    if results:
                        os.makedirs(model_dir, exist_ok=True)
                        _save_to_csv(results, csv_path)
                        stats['with_results'] += 1
                        logger.info(
                            f"    ✓ {len(results)} carro(s) guardados → {csv_path}"
                        )
                    else:
                        stats['empty'] += 1
                        logger.debug(f"    - Sem resultados para {brand_value}/{model_value}")

                    # Marcar como feito e persistir progresso
                    already_done.add(pair)
                    _save_progress(already_done)

                except KeyboardInterrupt:
                    logger.warning("Extração interrompida pelo utilizador. Progresso guardado.")
                    _save_progress(already_done)
                    _print_summary(logger, stats, total_models, start_time)
                    return stats

                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"    ✗ Erro em {brand_value}/{model_value}: {e}", exc_info=False)
                    # Delay extra depois de erro para evitar banimento
                    time.sleep(FULL_EXTRACTION_DELAY * 2)
                    continue

                # ── Delay entre requests ──────────────────────────────────────
                time.sleep(FULL_EXTRACTION_DELAY)

    _save_progress(already_done)
    _print_summary(logger, stats, total_models, start_time)
    return stats


def _print_summary(logger, stats: dict, total_models: int, start_time: float) -> None:
    elapsed_secs = int(time.time() - start_time)
    elapsed_str  = str(timedelta(seconds=elapsed_secs))
    processed    = stats['processed']
    avg_str = (
        f"{elapsed_secs / processed:.1f}s/modelo"
        if processed > 0 else "N/A"
    )
    models_hr = (
        f"{processed / (elapsed_secs / 3600):.0f} modelos/hora"
        if elapsed_secs > 0 and processed > 0 else "N/A"
    )

    logger.info("=" * 60)
    logger.info("EXTRAÇÃO COMPLETA — RESUMO FINAL")
    logger.info(f"  Total modelos na BD:    {total_models}")
    logger.info(f"  Processados:            {processed}")
    logger.info(f"    Com resultados:       {stats['with_results']}")
    logger.info(f"    Sem resultados:       {stats['empty']}")
    logger.info(f"  Saltados (já feitos):   {stats['skipped']}")
    logger.info(f"  Erros:                  {stats['errors']}")
    logger.info(f"  Tempo total:            {elapsed_str}")
    logger.info(f"  Média por modelo:       {avg_str}")
    logger.info(f"  Ritmo:                  {models_hr}")
    logger.info(f"  Output:                 {os.path.abspath(FULL_EXTRACTION_OUTPUT_DIR)}")
    logger.info(f"  Fim:                    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
