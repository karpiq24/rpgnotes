# core/config.py
"""
Gerenciamento de configurações e variáveis de ambiente
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import sys

class Config:
    """Classe para gerenciar configurações do sistema"""
    
    def __init__(self):
        """Inicializa configurações carregando variáveis de ambiente"""
        load_dotenv()
        self._setup_paths()
        self._setup_api_config()
        
    def _setup_paths(self):
        """Configura todos os caminhos do sistema"""
        # Diretórios principais
        self.OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
        self.TEMP_DIR = Path(os.getenv("TEMP_DIR", "./temp"))
        self.DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", "./downloads"))
        
        # Diretórios de origem
        self.CHAT_LOG_SOURCE_DIR = self.DOWNLOADS_DIR
        self.AUDIO_SOURCE_DIR = self.DOWNLOADS_DIR
        
        # Arquivos de configuração
        self.DISCORD_MAPPING_FILE = Path(os.getenv("DISCORD_MAPPING_FILE", "./discord_speaker_mapping.json"))
        self.WHISPER_PROMPT_FILE = Path(os.getenv("WHISPER_PROMPT_FILE", "./prompts/whisper.txt"))
        self.SUMMARY_PROMPT_FILE = Path(os.getenv("SUMMARY_PROMPT_FILE", "./prompts/summary-ootdl.txt"))
        self.DETAILS_PROMPT_FILE = Path(os.getenv("DETAILS_PROMPT_FILE", "./prompts/details.txt"))
        self.TEMPLATE_FILE = Path(os.getenv("TEMPLATE_FILE", "./template.md"))
        self.CONTEXT_DIR = Path(os.getenv("CONTEXT_DIR", "./prompts/pt"))
        
        # Diretórios de saída
        self.CHAT_LOG_OUTPUT_DIR = self.OUTPUT_DIR / "_chat_log"
        self.TRANSCRIPTIONS_OUTPUT_DIR = self.OUTPUT_DIR / "_transcripts"
        self.AUDIO_OUTPUT_DIR = self.TEMP_DIR / "audio"
        self.TEMP_TRANSCRIPTIONS = self.TEMP_DIR / "transcriptions"
    
    def _setup_api_config(self):
        """Configura APIs e modelos"""
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        self.GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-pro")
    
    def validate_required_files(self):
        """Valida se arquivos essenciais existem"""
        required_files = [
            self.DISCORD_MAPPING_FILE,
            self.TEMPLATE_FILE
        ]
        
        missing = [f for f in required_files if not f.exists()]
        if missing:
            print("❌ Arquivos obrigatórios não encontrados:")
            for f in missing:
                print(f" - {f}")
            print("\\n💡 Execute o setup inicial para criar os arquivos.")
            sys.exit(1)
    
    def setup_directories(self):
        """Cria todos os diretórios necessários"""
        directories = [
            self.OUTPUT_DIR, self.TEMP_DIR, self.CHAT_LOG_OUTPUT_DIR,
            self.AUDIO_OUTPUT_DIR, self.TRANSCRIPTIONS_OUTPUT_DIR,
            self.TEMP_TRANSCRIPTIONS, self.CONTEXT_DIR
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_paths_config(self):
        """Retorna dicionário com todos os caminhos configurados"""
        return {
            'output_dir': self.OUTPUT_DIR,
            'temp_dir': self.TEMP_DIR,
            'downloads_dir': self.DOWNLOADS_DIR,
            'discord_mapping': self.DISCORD_MAPPING_FILE,
            'template_file': self.TEMPLATE_FILE,
            'context_dir': self.CONTEXT_DIR
        }

def load_environment_config():
    """Função utilitária para carregar configuração rapidamente"""
    return Config()