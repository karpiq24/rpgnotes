# rpgnotes/core/session.py
"""
Classe principal para gerenciar sessões de RPG.
"""
import re
import json
import datetime
import shutil
from pathlib import Path
from typing import Optional, Tuple

from .config import Config
from .exceptions import FileProcessingError, ValidationError
from ..utils.file_handler import FileHandler
from ..utils.validators import SessionValidator


class RPGSession:
    """Classe que representa e gerencia uma sessão de RPG."""
    
    def __init__(self, config: Config, language: str, party: str, summary_template: Path):
        """
        Inicializa uma sessão de RPG.
        
        Args:
            config: Instância de configuração
            language: Código do idioma (en/pt) 
            party: Nome da party
            summary_template: Caminho para template de sumário
        """
        self.config = config
        self.language = language
        self.party = party
        self.summary_template = summary_template
        
        # Configuração específica do idioma
        self.lang_config = config.get_language_config(language, party)
        
        # Dados da sessão
        self.session_number: Optional[int] = None
        self.session_date: Optional[datetime.date] = None
        self.transcript_file: Optional[Path] = None
        
        # Handlers
        self.file_handler = FileHandler()
        self.validator = SessionValidator()
        
        # Setup inicial
        self.config.setup_directories()
    
    def process_chat_log(self) -> Tuple[Optional[int], Optional[datetime.date]]:
        """
        Processa o log de chat mais recente.
        
        Returns:
            Tupla com (número_sessão, data_sessão)
        """
        try:
            # Encontra o arquivo mais recente
            newest_chat_log = self.file_handler.get_newest_file(
                self.config.downloads_dir, 
                "session*.json"
            )
            
            if not newest_chat_log:
                raise FileProcessingError("Nenhum log de chat encontrado (formato: session*.json)")
            
            # Extrai número da sessão
            match = re.search(r'session(\d+)', newest_chat_log.name)
            if not match:
                raise FileProcessingError(f"Não foi possível extrair número da sessão de: {newest_chat_log.name}")
            
            session_number = int(match.group(1))
            
            # Extrai data da sessão
            session_date = self._extract_date_from_chat_log(newest_chat_log)
            
            # Verifica se já foi processado
            output_filepath = self.config.chat_log_output_dir / f"session{session_number}.json"
            if output_filepath.exists():
                print(f"Chat log para sessão {session_number} já existe. Pulando processamento.")
                return session_number, session_date
            
            # Processa e salva
            prettified_json = self.file_handler.prettify_json(newest_chat_log)
            if prettified_json:
                self.file_handler.save_json_string(prettified_json, output_filepath)
                print(f"Chat log processado e salvo em: {output_filepath}")
            
            self.session_number = session_number
            self.session_date = session_date
            
            return session_number, session_date
            
        except Exception as e:
            raise FileProcessingError(f"Erro ao processar chat log: {e}")
    
    def _extract_date_from_chat_log(self, chat_log_file: Path) -> Optional[datetime.date]:
        """Extrai data do arquivo de chat log."""
        try:
            with open(chat_log_file, 'r', encoding='utf-8') as f:
                log_data = json.load(f)
            
            date_str = log_data.get("archiveDate")
            if date_str:
                return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"Aviso: Não foi possível extrair data do chat log {chat_log_file.name}: {e}")
        
        return None
    
    def prepare_audio_files(self):
        """Prepara arquivos de áudio para transcrição."""
        from ..audio.processor import AudioProcessor
        
        processor = AudioProcessor(self.config)
        processor.unzip_audio()
    
    def transcribe_audio(self):
        """Transcreve arquivos de áudio."""
        from ..audio.transcriber import AudioTranscriber
        
        transcriber = AudioTranscriber(self.config)
        transcriber.transcribe_all_audio()
    
    def combine_transcriptions(self) -> Optional[Path]:
        """
        Combina transcrições individuais em um arquivo único.
        
        Returns:
            Caminho para arquivo de transcrição combinada
        """
        if not self.session_number:
            raise ValidationError("Número da sessão não definido")
        
        from ..audio.transcriber import AudioTranscriber
        
        transcriber = AudioTranscriber(self.config)
        transcript_file = transcriber.combine_transcriptions(self.session_number)
        
        self.transcript_file = transcript_file
        return transcript_file
    
    def generate_ai_notes(self) -> Optional[Tuple[str, object]]:
        """
        Gera notas usando IA.
        
        Returns:
            Tupla com (sumário, dados_estruturados)
        """
        if not self.transcript_file:
            raise ValidationError("Arquivo de transcrição não definido")
        
        from ..ai.gemini_client import GeminiClient
        
        client = GeminiClient(self.config, self.lang_config, self.summary_template)
        return client.generate_session_notes(self.transcript_file)
    
    def save_notes(self, summary: str, structured_data: object):
        """
        Salva as notas processadas.
        
        Args:
            summary: Sumário da sessão
            structured_data: Dados estruturados extraídos
        """
        if not all([self.session_number, self.session_date]):
            raise ValidationError("Dados da sessão incompletos")
        
        from ..utils.formatters import NotesFormatter
        
        formatter = NotesFormatter(self.config)
        formatter.save_formatted_notes(
            summary, 
            structured_data, 
            self.session_number, 
            self.session_date
        )
    
    def cleanup_temp_files(self):
        """Remove arquivos temporários se configurado."""
        if self.config.delete_temp_files and self.config.temp_dir.exists():
            try:
                shutil.rmtree(self.config.temp_dir)
                print(f"Arquivos temporários removidos: {self.config.temp_dir}")
            except Exception as e:
                print(f"Erro ao remover arquivos temporários: {e}")
    
    def run_transcription_workflow(self) -> Optional[Tuple[Path, int, datetime.date]]:
        """
        Executa workflow até a transcrição.
        
        Returns:
            Tupla com (arquivo_transcrição, número_sessão, data_sessão)
        """
        print("\n[Passo 1/4] Processando Chat Log...")
        session_number, session_date = self.process_chat_log()
        
        if not session_number:
            print("❌ Erro ao processar chat log.")
            return None
        
        print(f"✅ Sessão {session_number} - {session_date}")
        
        print("\n[Passo 2/4] Preparando Arquivos de Áudio...")
        self.prepare_audio_files()
        print("✅ Áudio preparado.")
        
        print("\n[Passo 3/4] Transcrevendo Áudio...")
        self.transcribe_audio()
        print("✅ Transcrição concluída.")
        
        print("\n[Passo 4/4] Combinando Transcrições...")
        transcript_file = self.combine_transcriptions()
        
        if not transcript_file:
            print("❌ Erro ao combinar transcrições.")
            return None
        
        print("✅ Transcrições combinadas.")
        return transcript_file, session_number, session_date
    
    def run_full_workflow(self):
        """Executa workflow completo incluindo IA."""
        result = self.run_transcription_workflow()
        
        if not result:
            return
        
        transcript_file, session_number, session_date = result
        
        print("\n[Passo 5/5] Gerando Notas com IA...")
        notes = self.generate_ai_notes()
        
        if notes:
            summary, structured_data = notes
            self.save_notes(summary, structured_data)
            print("✅ Notas geradas e salvas com sucesso.")
        else:
            print("⚠️ Geração de notas com IA foi pulada ou falhou.")
        
        # Limpeza opcional
        self.cleanup_temp_files()
        
        print("\n✨ Workflow completo finalizado! ✨")