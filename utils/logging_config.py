import logging
import os
from datetime import datetime

class FlushingFileHandler(logging.FileHandler):
    """Handler que força a escrita no disco a cada mensagem"""
    def emit(self, record):
        super().emit(record)
        self.flush()

def setup_logging():
    """
    Configura o sistema de logging para substituir prints.
    Limpa o ficheiro de log a cada nova execução.
    """
    # Diretório de logs
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Ficheiro de log
    log_file = os.path.join(log_dir, "scraping.log")
    
    # Limpa o ficheiro de log (nova sessão)
    if os.path.exists(log_file):
        open(log_file, 'w').close()
    
    # Configuração do logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            # Usa o handler personalizado para garantir escrita imediata
            FlushingFileHandler(log_file, encoding='utf-8'),
            # Sem StreamHandler para não sujar a consola (os outputs JSON saem limpos)
        ]
    )
    
    # Log inicial
    logger = logging.getLogger(__name__)
    logger.info("="*50)
    logger.info("SESSÃO DE SCRAPING OTOMOTO INICIADA")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*50)
    
    return logger

def get_logger(name):
    """Retorna um logger para o módulo especificado"""
    return logging.getLogger(name)