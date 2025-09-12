# rpgnotes/ai/gemini_client.py
"""
Cliente para interação com a API do Google Gemini.
"""
import time
from pathlib import Path
from typing import Tuple, Optional

import google.generativeai as genai
import instructor

from .models import SessionData
from ..core.config import Config
from ..core.exceptions import AIGenerationError


class GeminiClient:
    """Cliente para gerar conteúdo usando Google Gemini."""
    
    def __init__(self, config: Config, lang_config: dict, summary_template: Path):
        """
        Inicializa o cliente Gemini.
        
        Args:
            config: Configuração principal
            lang_config: Configuração específica do idioma
            summary_template: Template de sumário escolhido
        """
        self.config = config
        self.lang_config = lang_config
        self.summary_template = summary_template
        
        # Configura a API
        genai.configure(api_key=config.gemini_api_key)
        
        # Carrega prompts
        self._load_prompts()
    
    def _load_prompts(self):
        """Carrega os prompts necessários."""
        try:
            # Prompt de sumário do template escolhido
            with open(self.summary_template, 'r', encoding='utf-8') as f:
                self.summary_prompt = f.read().strip()
            
            # Prompt de detalhes
            self.details_prompt = self.config.get_prompt_content('details')
            
        except Exception as e:
            raise AIGenerationError(f"Erro ao carregar prompts: {e}")
    
    def generate_session_notes(self, transcript_file: Path) -> Optional[Tuple[str, SessionData]]:
        """
        Gera notas da sessão usando IA.
        
        Args:
            transcript_file: Arquivo de transcrição
            
        Returns:
            Tupla com (sumário, dados_estruturados)
        """
        if not self.config.gemini_api_key:
            print("GEMINI_API_KEY não configurada. Pulando geração de notas.")
            return None
        
        try:
            # Carrega transcrição
            with open(transcript_file, 'r', encoding='utf-8') as f:
                transcript_content = f.read()
            
            # Gera sumário detalhado
            print("Gerando sumário detalhado da sessão...")
            summary = self._generate_summary(transcript_content)
            
            # Aguarda para respeitar rate limits
            print("Aguardando rate limit da API...")
            time.sleep(10)
            
            # Extrai dados estruturados
            print("Extraindo detalhes estruturados...")
            structured_data = self._extract_structured_details(summary, transcript_content)
            
            print("Notas geradas com sucesso.")
            return summary, structured_data
            
        except Exception as e:
            raise AIGenerationError(f"Erro na geração de notas: {e}")
    
    def _generate_summary(self, transcript_content: str) -> str:
        """Gera sumário narrativo da sessão."""
        try:
            summary_model = genai.GenerativeModel(
                model_name=self.config.gemini_model_name,
                system_instruction=self.summary_prompt,
            )
            
            messages = []
            
            # Adiciona contexto se disponível
            if self.lang_config.get('context_data'):
                messages.append({
                    "role": "user", 
                    "parts": [f"CONTEXTO ADICIONAL DA CAMPANHA:\n{self.lang_config['context_data']}"]
                })
            
            # Adiciona transcrição
            messages.append({
                "role": "user", 
                "parts": [f"TRANSCRIÇÃO DA SESSÃO ATUAL:\n{transcript_content}"]
            })
            
            response = summary_model.generate_content(
                messages,
                generation_config=genai.GenerationConfig(temperature=0.7),
            )
            
            return response.text
            
        except Exception as e:
            raise AIGenerationError(f"Erro ao gerar sumário: {e}")
    
    def _extract_structured_details(self, summary: str, transcript_content: str) -> SessionData:
        """Extrai dados estruturados da sessão."""
        try:
            client = instructor.from_gemini(
                client=genai.GenerativeModel(
                    model_name=self.config.gemini_model_name,
                    system_instruction=self.details_prompt,
                ),
                mode=instructor.Mode.GEMINI_JSON,
            )
            
            message_content = (
                f"SUMÁRIO DA SESSÃO (use para gerar título, eventos, NPCs, locais, itens e propostas):\n{summary}\n\n"
                f"TRANSCRIÇÃO COMPLETA (use APENAS para encontrar citações exatas):\n{transcript_content}"
            )
            
            session_data = client.chat.completions.create(
                messages=[{
                    "role": "user",
                    "content": message_content
                }],
                response_model=SessionData,
                max_retries=3,
            )
            
            return session_data
            
        except Exception as e:
            raise AIGenerationError(f"Erro na extração de detalhes: {e}")