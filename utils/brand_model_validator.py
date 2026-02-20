import json
import os
from utils.config import DATABASE_PATH

class BrandModelValidator:
    def __init__(self):
        self.data = self._load_database()
        self.brands = self.data.get('brands', {})

    def _load_database(self):
        try:
            if not os.path.exists(DATABASE_PATH):
                print(f"AVISO: Base de dados não encontrada em {DATABASE_PATH}")
                return {"brands": {}}
            
            with open(DATABASE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar base de dados: {e}")
            return {"brands": {}}

    def validate_search_params(self, marca_input, modelo_input):
        result = {
            'valid': True,
            'brand_value': None,
            'model_value': None,
            'errors': [],
            'suggestions': {}
        }

        if not marca_input:
            return result

        # 1. Validar Marca
        brand_found = None
        marca_lower = marca_input.lower().strip()
        
        # Procura nas chaves e nos valores 'brand_text'/'brand_value'
        for key, data in self.brands.items():
            if (key.lower() == marca_lower or 
                data.get('brand_value') == marca_lower or 
                data.get('brand_text', '').lower() == marca_lower):
                brand_found = data
                result['brand_value'] = data['brand_value']
                break
        
        if not brand_found:
            result['valid'] = False
            result['errors'].append(f"Marca '{marca_input}' não encontrada.")
            # Sugestões simples (primeiras 5 marcas)
            result['suggestions']['marcas'] = list(self.brands.keys())[:5]
            return result

        # 2. Validar Modelo (se fornecido)
        if modelo_input:
            model_found = None
            modelo_lower = modelo_input.lower().strip()
            
            # A tua DB tem uma lista de dicionários em 'models'
            models_list = brand_found.get('models', [])
            
            for model in models_list:
                if (model['text'].lower() == modelo_lower or 
                    model['value'].lower() == modelo_lower):
                    model_found = model
                    result['model_value'] = model['value']
                    break
            
            if not model_found:
                result['valid'] = False
                result['errors'].append(f"Modelo '{modelo_input}' não encontrado para a marca.")
                result['suggestions']['modelos_disponiveis'] = [m['text'] for m in models_list]

        return result

validator = BrandModelValidator()