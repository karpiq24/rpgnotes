# rpgnotes/core/config.py
"""
Gerenciador de configurações centralizado para RPG Notes.
"""
import os
import json
from pathlib import Path
from typing import Dict, Optional, List
from dotenv import load_dotenv
from .exceptions import ConfigurationError

class Config:
    """Classe centralizada para gerenciar todas as configurações."""
    
    def __init__(self, env_file: Optional[str] = None):
        """
        Inicializa as configurações.
        
        Args:
            env_file: Caminho para arquivo .env personalizado
        """
        # Carrega variáveis de ambiente
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()
        
        # Configuração de diretórios base
        self.project_root = Path(__file__).parent.parent.parent
        
        # Configurações principais
        self._load_core_config()
        self._load_api_config()
        self._load_directory_config()
        
        # Validação inicial
        self._validate_config()
    
    def _load_core_config(self):
        """Carrega configurações principais."""
        self.gemini_model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-pro")
        self.delete_temp_files = os.getenv("DELETE_TEMP_FILES", "false").lower() == "true"
        
    def _load_api_config(self):
        """Carrega configurações da API."""
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not self.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY é obrigatória no arquivo .env")
    
    def _load_directory_config(self):
        """Configura todos os diretórios."""
        # Diretórios principais
        self.output_dir = Path(os.getenv("OUTPUT_DIR", "./output"))
        self.temp_dir = Path(os.getenv("TEMP_DIR", "./temp"))
        self.downloads_dir = Path(os.getenv("DOWNLOADS_DIR", "./downloads"))
        
        # Subdiretórios organizacionais
        self.chat_log_output_dir = self.output_dir / "_chat_log"
        self.transcriptions_output_dir = self.output_dir / "_transcripts"
        self.audio_output_dir = self.temp_dir / "audio"
        self.temp_transcriptions = self.temp_dir / "transcriptions"
        
        # Diretórios de configuração
        self.config_dir = Path(os.getenv("CONFIG_DIR", "./config"))
        self.languages_dir = self.config_dir / "languages"
        self.prompts_dir = self.config_dir / "prompts"
        
    def _validate_config(self):
        """Valida se configurações essenciais estão presentes."""
        required_dirs = [
            self.config_dir,
            self.languages_dir / "pt",
            self.languages_dir / "en",
            self.prompts_dir
        ]
        
        missing_dirs = [d for d in required_dirs if not d.exists()]
        if missing_dirs:
            dirs_str = ", ".join(str(d) for d in missing_dirs)
            raise ConfigurationError(f"Diretórios obrigatórios não encontrados: {dirs_str}")
    
    def setup_directories(self):
        """Cria todos os diretórios necessários."""
        directories = [
            self.output_dir,
            self.temp_dir,
            self.chat_log_output_dir,
            self.transcriptions_output_dir,
            self.audio_output_dir,
            self.temp_transcriptions
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_language_config(self, language: str, party: str) -> Dict:
        """
        Obtém configuração específica do idioma e party.
        
        Args:
            language: Código do idioma (en/pt)
            party: Nome da party
            
        Returns:
            Dict com configurações do idioma
        """
        lang_dir = self.languages_dir / language
        
        if not lang_dir.exists():
            raise ConfigurationError(f"Idioma '{language}' não suportado")
        
        # Carrega arquivos de contexto
        context_files = {
            'main': lang_dir / "main.txt",
            'characters': lang_dir / "characters.txt", 
            'places': lang_dir / "places.txt"
        }
        
        context_data = f"PARTY: {party}\n\n"
        
        for file_type, file_path in context_files.items():
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    context_data += f"--- {file_type.upper()} ---\n{f.read()}\n\n"
        
        return {
            'context_dir': lang_dir,
            'context_data': context_data,
            'language_code': language
        }
    
    def get_summary_templates(self) -> List[Path]:
        """Retorna lista de templates de sumário disponíveis."""
        summary_dir = self.prompts_dir / "summary_templates"
        if not summary_dir.exists():
            # Fallback para estrutura atual
            return sorted(self.project_root.glob("prompts/summary-*.txt"))
        return sorted(summary_dir.glob("*.txt"))
    
    def get_discord_mapping(self) -> Dict[str, str]:
        """Carrega mapeamento Discord -> Personagem."""
        mapping_file = self.config_dir / "discord_mapping.json"
        
        if not mapping_file.exists():
            # Fallback para arquivo na raiz
            mapping_file = self.project_root / "discord_speaker_mapping.json"
        
        if not mapping_file.exists():
            return {}
        
        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def get_prompt_content(self, prompt_name: str) -> str:
        """
        Obtém conteúdo de um prompt específico.
        
        Args:
            prompt_name: Nome do arquivo do prompt (sem extensão)
            
        Returns:
            Conteúdo do prompt
        """
        prompt_file = self.prompts_dir / f"{prompt_name}.txt"
        
        if not prompt_file.exists():
            # Fallback para estrutura atual
            prompt_file = self.project_root / "prompts" / f"{prompt_name}.txt"
        
        if not prompt_file.exists():
            raise ConfigurationError(f"Prompt '{prompt_name}' não encontrado")
        
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    
    def get_template_content(self) -> str:
        """Obtém conteúdo do template de notas."""
        template_file = self.config_dir / "template.md"
        
        if not template_file.exists():
            # Fallback para arquivo na raiz
            template_file = self.project_root / "template.md"
        
        if not template_file.exists():
            raise ConfigurationError("Template de notas não encontrado")
        
        with open(template_file, 'r', encoding='utf-8') as f:
            return f.read()