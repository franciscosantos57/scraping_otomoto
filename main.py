#!/usr/bin/env python3
"""
Otomoto Car Scraper
Sistema de scraping para o site otomoto.pl, permitindo pesquisas avançadas e extração completa de dados.
"""

import sys
import json
import argparse
from scraper.otomoto_scraper import OtomotoScraper
from models.car import CarSearchParams
from utils.helpers import calculate_price_interval
from utils.brand_model_validator import validator
from utils.logging_config import setup_logging, get_logger
from utils.full_extraction import run_full_extraction

def create_search_params():
    """
    Cria objeto de parâmetros a partir dos argumentos da linha de comando.
    Retorna (CarSearchParams, args) — args contém flags como --full-extraction.
    """
    parser = argparse.ArgumentParser(description='Otomoto Scraper')
    parser.add_argument('--full_extraction', action='store_true',
                        help='Extração completa: scraping de todas as marcas e modelos (output em cars/)')
    parser.add_argument('--marca', type=str, help='Marca (ex: bmw)')
    parser.add_argument('--modelo', type=str, help='Modelo (ex: x5)')
    parser.add_argument('--ano_min', type=int, help='Ano mínimo')
    parser.add_argument('--ano_max', type=int, help='Ano máximo')
    parser.add_argument('--km_max', type=int, help='KM máximo')
    parser.add_argument('--preco_max', type=int, help='Preço máximo')
    parser.add_argument('--caixa', type=str, choices=['manual', 'automatica'], help='Tipo de caixa')
    parser.add_argument('--combustivel', type=str, 
                        choices=['gasolina', 'gasoleo', 'diesel', 'gpl', 'hibrido', 'eletrico', 'hidrogenio'], 
                        help='Tipo de combustível')
    
    args = parser.parse_args()
    
    search_params = CarSearchParams(
        marca=args.marca,
        modelo=args.modelo,
        ano_min=args.ano_min,
        ano_max=args.ano_max,
        km_max=args.km_max,
        preco_max=args.preco_max,
        caixa=args.caixa,
        combustivel=args.combustivel
    )
    return search_params, args

def main():
    # 1. Configurar Logging (escreve em logs/scraping.log)
    setup_logging()
    logger = get_logger(__name__)
    
    # Estrutura de output padrão em caso de erro
    empty_output = {
        "preco_intervalo": {"min": None, "max": None},
        "media_aproximada": None,
        "viaturas_consideradas": 0,
        "anuncios_usados_para_calculo": []
    }

    try:
        logger.info("Iniciando scraping do Otomoto...")
        
        # 2. Obter parâmetros
        params, args = create_search_params()

        # --- Extração Completa -------------------------------------------
        if args.full_extraction:
            logger.info("Modo de extração completa activado.")
            run_full_extraction()
            return
        # -----------------------------------------------------------------

        logger.info(f"Parâmetros recebidos: {params.__dict__}")

        # 3. Validação e Normalização (usando otomoto_database.json)
        if params.marca:
            val_result = validator.validate_search_params(params.marca, params.modelo)
            
            if val_result['valid']:
                # Atualiza com os valores oficiais da base de dados (ex: "BMW" -> "bmw")
                if val_result['brand_value']:
                    logger.info(f"Marca normalizada: '{params.marca}' -> '{val_result['brand_value']}'")
                    params.marca = val_result['brand_value']
                
                if val_result['model_value']:
                    logger.info(f"Modelo normalizado: '{params.modelo}' -> '{val_result['model_value']}'")
                    params.modelo = val_result['model_value']
            else:
                logger.error(f"Erro de validação: {val_result['errors']}")
                
                # Retorna JSON de erro para o utilizador
                error_output = empty_output.copy()
                error_output["erro"] = "Parâmetros inválidos"
                error_output["detalhes"] = val_result['errors']
                error_output["sugestoes"] = val_result.get('suggestions')
                
                print(json.dumps(error_output, indent=2, ensure_ascii=False))
                sys.exit(1)

        # 4. Iniciar Scraping
        with OtomotoScraper() as scraper:
            logger.info("Iniciando pesquisa no site...")
            results = scraper.search_cars(params)
            
            if not results:
                logger.warning("Nenhum carro encontrado com os critérios fornecidos.")
                print(json.dumps(empty_output, indent=2, ensure_ascii=False))
                return

            # Logs informativos sobre carros encontrados
            logger.info(f"Total de {len(results)} carros extraídos")
            logger.info(f"{len(results)} carros únicos após deduplicação (só URLs)")
            logger.info(f"{len(results)} carros prontos")
            logger.info(f"{len(results)} carros com dados válidos")
            
            # 5. Listar todos os carros encontrados
            logger.info("=== CARROS ENCONTRADOS ===")
            for idx, car in enumerate(results, 1):
                # Formata o número com espaço de padding (ex: "  1.", " 10.", "100.")
                car_num_str = f"{idx:3d}."
                # Formata o preço com espaço antes da moeda
                price_str = f"{car.preco_numerico:.0f} {car.moeda}"
                logger.info(f"{car_num_str} {car.titulo} → {price_str}")
            logger.info(f"=== TOTAL: {len(results)} CARROS ===")
            
            # 6. Calcular Estatísticas
            output = calculate_price_interval(results)
            
            # Logs finais com estatísticas
            logger.info(f"Encontrados {len(results)} carros")
            logger.info(f"Calculando intervalo de preços para {len(results)} carros")
            
            # Análise de outliers (adoptando a lógica de calculate_price_interval)
            prices = [c.preco_numerico for c in results if c.preco_numerico > 100]
            if prices:
                prices_sorted = sorted(prices)
                q1_idx = int(len(prices_sorted) * 0.25)
                q3_idx = int(len(prices_sorted) * 0.75)
                q1 = prices_sorted[q1_idx] if q1_idx < len(prices_sorted) else prices_sorted[0]
                q3 = prices_sorted[q3_idx] if q3_idx < len(prices_sorted) else prices_sorted[-1]
                iqr = q3 - q1
                lower_limit = q1 - 1.5 * iqr
                upper_limit = q3 + 1.5 * iqr
                
                moeda = results[0].moeda if results else ''
                logger.info(f"Análise de outliers: Q1={q1:.0f}€, Q3={q3:.0f}€, IQR={iqr:.0f}€")
                logger.info(f"Limites: {lower_limit:.0f}€ - {upper_limit:.0f}€")
                
                outliers = [c for c in results if c.preco_numerico < lower_limit or c.preco_numerico > upper_limit]
                if outliers:
                    logger.info(f"Detectados {len(outliers)} outliers.")
                else:
                    logger.info("Nenhum outlier detectado. Todos os preços estão dentro do intervalo normal.")
            
            logger.info(f"Intervalo final: {output['preco_intervalo']['min']:.0f}€ - {output['preco_intervalo']['max']:.0f}€ (média: {output['media_aproximada']:.0f}€)")
            logger.info(f"Carros considerados: {output['viaturas_consideradas']} (removidos {len(results) - output['viaturas_consideradas']} outliers)")
            logger.info(f"Total de carros: {len(results)}")
            logger.info(f"Carros considerados: {output['viaturas_consideradas']}")
            logger.info(f"Média aproximada: {output['media_aproximada']}€")
            logger.info(f"Intervalo de preços: {output['preco_intervalo']['min']:.0f}€ - {output['preco_intervalo']['max']:.0f}€")
            
            # 7. Output Final (JSON para stdout)
            print(json.dumps(output, indent=2, ensure_ascii=False))

    except KeyboardInterrupt:
        logger.warning("Operação cancelada pelo utilizador.")
        print(json.dumps(empty_output, indent=2, ensure_ascii=False))
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Erro crítico durante a execução: {str(e)}", exc_info=True)
        print(json.dumps(empty_output, indent=2, ensure_ascii=False))
        sys.exit(1)

if __name__ == "__main__":
    main()