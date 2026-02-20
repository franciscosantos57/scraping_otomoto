def calculate_price_interval(cars):
    if not cars:
        return {
            "preco_intervalo": {"min": None, "max": None},
            "media_aproximada": None,
            "viaturas_consideradas": 0
        }
    
    # Filtrar preços zero ou inválidos
    prices = [c.preco_numerico for c in cars if c.preco_numerico > 100]
    
    if not prices:
        return {
            "preco_intervalo": {"min": None, "max": None},
            "media_aproximada": None,
            "viaturas_consideradas": 0
        }

    prices.sort()
    
    # Remover outliers simples (5% mais baratos e 5% mais caros)
    cut = int(len(prices) * 0.05)
    if cut > 0:
        clean_prices = prices[cut:-cut]
    else:
        clean_prices = prices
        
    if not clean_prices:
        clean_prices = prices

    avg = sum(clean_prices) / len(clean_prices)
    
    return {
        "preco_intervalo": {
            "min": min(clean_prices),
            "max": max(clean_prices)
        },
        "media_aproximada": round(avg, 2),
        "viaturas_consideradas": len(clean_prices),
        "anuncios_usados_para_calculo": [c.to_dict() for c in cars if c.preco_numerico in clean_prices]
    }