from dataclasses import dataclass
from typing import Optional

@dataclass
class CarSearchParams:
    """Parâmetros para pesquisa de carros"""
    marca: Optional[str] = None
    modelo: Optional[str] = None
    ano_min: Optional[int] = None
    ano_max: Optional[int] = None
    km_max: Optional[int] = None
    preco_max: Optional[int] = None
    caixa: Optional[str] = None
    combustivel: Optional[str] = None

@dataclass
class Car:
    """Representação de um carro encontrado"""
    titulo: str
    preco: str
    preco_numerico: float
    moeda: str = "PLN" # Default Otomoto
    ano: Optional[int] = None
    quilometragem: Optional[str] = None
    combustivel: Optional[str] = None
    url: Optional[str] = None

    def to_dict(self):
        return {
            'Título': self.titulo,
            'Preço': self.preco,
            'Moeda': self.moeda,
            'Ano': self.ano,
            'Quilometragem': self.quilometragem,
            'Combustível': self.combustivel,
            'URL': self.url
        }