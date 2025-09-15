# core/session_manager.py
"""
Gerenciamento de sessões e processamento de chat logs
"""

__all__ = ["SessionManager"]

import re
import json
import datetime
import os
from pathlib import Path
from typing import Optional, Tuple

class SessionManager:
    """Classe para gerenciar sessões de RPG e processar logs"""
    
    def __init__(self, config):
        """
        Inicializa o gerenciador de sessões
        
        Args:
            config: Instância de Config com configurações do sistema
        """
        self.config = config
    
    def process_chat_log(self) -> Optional[Tuple[int, datetime.date]]:
        """
        Processa log de chat se disponível, senão usa data atual e número sequencial
        
        Returns:
            Tuple[int, datetime.date]: (session_number, session_date) ou None se erro
        """
        print("🔍 Procurando logs de chat...")
        
        # Tenta encontrar arquivo session*.json
        newest_chat_log = self._get_newest_file(
            self.config.CHAT_LOG_SOURCE_DIR, 
            "session*.json"
        )
        
        if newest_chat_log:
            print(f"📄 Encontrado chat log: {newest_chat_log.name}")
            return self._extract_session_info_from_file(newest_chat_log)
        else:
            print("📅 Nenhum session*.json encontrado. Gerando baseado na data atual...")
            return self._generate_session_from_date()
    
    def _get_newest_file(self, directory: Path, pattern: str) -> Optional[Path]:
        """
        Encontra o arquivo mais recente que corresponde ao padrão
        
        Args:
            directory: Diretório para procurar
            pattern: Padrão de arquivo (ex: "session*.json")
            
        Returns:
            Path: Caminho para arquivo mais recente ou None
        """
        try:
            files = list(directory.glob(pattern))
            if files:
                return max(files, key=os.path.getmtime)
            return None
        except Exception as e:
            print(f"⚠️ Erro ao buscar arquivos: {e}")
            return None
    
    def _extract_session_info_from_file(self, chat_log_file: Path) -> Optional[Tuple[int, datetime.date]]:
        """
        Extrai número e data da sessão do arquivo de chat log
        
        Args:
            chat_log_file: Caminho para arquivo de chat log
            
        Returns:
            Tuple[int, datetime.date]: (session_number, session_date) ou None
        """
        try:
            # Extrai número da sessão do nome do arquivo
            match = re.search(r'session(\d+)', chat_log_file.name)
            if not match:
                print(f"⚠️ Não foi possível extrair número da sessão de: {chat_log_file.name}")
                return None
            
            session_number = int(match.group(1))
            
            # Tenta extrair data do conteúdo do arquivo
            session_date = self._extract_date_from_chat_log(chat_log_file)
            
            if not session_date:
                # Usa data de modificação do arquivo como fallback
                session_date = datetime.date.fromtimestamp(chat_log_file.stat().st_mtime)
                print(f"⚠️ Data extraída da modificação do arquivo: {session_date}")
            
            print(f"✅ Sessão {session_number}, Data: {session_date}")
            return session_number, session_date
            
        except Exception as e:
            print(f"❌ Erro ao processar chat log: {e}")
            return None
    
    def _extract_date_from_chat_log(self, chat_log_file: Path) -> Optional[datetime.date]:
        """
        Extrai data do conteúdo do arquivo de chat log
        
        Args:
            chat_log_file: Caminho para arquivo de chat log
            
        Returns:
            datetime.date: Data extraída ou None se não encontrada
        """
        try:
            with open(chat_log_file, 'r', encoding='utf-8') as f:
                log_data = json.load(f)
            
            # Procura por campos de data comuns
            date_fields = ["archiveDate", "date", "timestamp", "created_at"]
            
            for field in date_fields:
                if field in log_data:
                    date_str = log_data[field]
                    if isinstance(date_str, str):
                        # Tenta diferentes formatos de data
                        date_formats = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]
                        
                        for fmt in date_formats:
                            try:
                                return datetime.datetime.strptime(date_str.split('T')[0], "%Y-%m-%d").date()
                            except ValueError:
                                continue
            
            print(f"⚠️ Nenhuma data válida encontrada no chat log")
            return None
            
        except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
            print(f"⚠️ Erro ao ler chat log: {e}")
            return None
    
    def _generate_session_from_date(self) -> Tuple[int, datetime.date]:
        """
        Gera número de sessão baseado na data atual
        
        Returns:
            Tuple[int, datetime.date]: (session_number, session_date)
        """
        today = datetime.date.today()
        
        # Usa formato YYYYMMDD como número da sessão
        session_number = int(today.strftime("%Y%m%d"))
        
        print(f"✅ Sessão gerada: {session_number}")
        print(f"✅ Data: {today}")
        
        return session_number, today
    
    def get_session_stats(self, session_number: int) -> dict:
        """
        Retorna estatísticas de uma sessão específica
        
        Args:
            session_number: Número da sessão
            
        Returns:
            dict: Estatísticas da sessão
        """
        stats = {
            'session_number': session_number,
            'files_found': {},
            'transcription_exists': False,
            'notes_exist': False
        }
        
        # Verifica se transcrição existe
        transcript_file = self.config.TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.txt"
        if transcript_file.exists():
            stats['transcription_exists'] = True
            stats['files_found']['transcript'] = str(transcript_file)
        
        # Verifica se notas finais existem
        notes_files = list(self.config.OUTPUT_DIR.glob(f"*{session_number}*.md"))
        if notes_files:
            stats['notes_exist'] = True
            stats['files_found']['notes'] = [str(f) for f in notes_files]
        
        return stats

def create_session_manager(config):
    """Função utilitária para criar instância do session manager"""
    return SessionManager(config)