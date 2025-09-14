# core/workflows.py
"""
Orquestração dos workflows principais do sistema - Versão Corrigida
"""
from pathlib import Path
from typing import Optional, Tuple
from datetime import date

class WorkflowManager:
    """Classe para gerenciar os workflows principais"""
    
    def __init__(self, config, transcriber, speaker_mapper, audio_processor, gemini_client):
        """
        Inicializa o gerenciador de workflows
        
        Args:
            config: Instância de Config
            transcriber: Instância de WhisperTranscriber
            speaker_mapper: Instância de SpeakerMapper
            audio_processor: Instância de AudioProcessor
            gemini_client: Instância de GeminiClient
        """
        self.config = config
        self.transcriber = transcriber
        self.speaker_mapper = speaker_mapper
        self.audio_processor = audio_processor
        self.gemini_client = gemini_client
    
    def run_transcription_workflow(self) -> Optional[Tuple[int, date]]:
        """
        Executa workflow de transcrição completo
        
        Returns:
            Tuple[int, date]: (session_number, session_date) ou None se erro
        """
        print("\\n🚀 INICIANDO WORKFLOW DE TRANSCRIÇÃO")
        print("=" * 50)
        
        # Passo 1: Processar informações da sessão
        print("\\n[Passo 1/4] Processando informações da sessão...")
        session_info = self._process_session_info()
        if not session_info:
            print("❌ Erro ao determinar informações da sessão.")
            return None
        
        session_number, session_date = session_info
        print(f"✅ Sessão: {session_number}")
        print(f"✅ Data: {session_date.strftime('%Y-%m-%d')}")
        
        # Passo 2: Extrair arquivos de áudio
        print("\\n[Passo 2/4] Extraindo arquivos de áudio...")
        if not self.audio_processor.extract_audio_files():
            print("❌ Erro ao extrair arquivos de áudio.")
            return None
        print("✅ Arquivos de áudio prontos para transcrição!")
        
        # Passo 3: Transcrição de áudio
        print("\\n[Passo 3/4] Transcrição de áudio...")
        if not self.transcriber.transcribe_audio():
            print("❌ Erro na transcrição. Abortando workflow.")
            return None
        print("✅ Transcrição concluída com sucesso.")
        
        # Passo 4: Combinação de transcrições
        print("\\n[Passo 4/4] Combinação de transcrições...")
        transcript_file = self.speaker_mapper.combine_transcriptions(session_number)
        if not transcript_file:
            print("❌ Erro ao combinar transcrições.")
            return None
        
        # Verificar se arquivo tem conteúdo
        if not self._validate_transcript_content(transcript_file):
            print("❌ Arquivo de transcrição está vazio.")
            return None
        
        print("\\n✨ WORKFLOW DE TRANSCRIÇÃO CONCLUÍDO! ✨")
        return session_number, session_date
    
    def run_full_workflow(self) -> bool:
        """
        Executa workflow completo incluindo geração de IA
        
        Returns:
            bool: True se workflow foi bem-sucedido
        """
        print("\\n🚀 INICIANDO WORKFLOW COMPLETO")
        print("=" * 50)
        
        # Executa workflow de transcrição
        result = self.run_transcription_workflow()
        if not result:
            return False
        
        session_number, session_date = result
        
        # Passo 5: Geração de notas com IA
        print("\\n[Passo 5/5] Geração de notas com IA...")
        transcript_file = self.config.TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.txt"
        
        try:
            notes = self.gemini_client.generate_session_notes(transcript_file)
            if notes:
                summary, structured_data = notes
                self.gemini_client.save_summary_file(summary, structured_data, session_number, session_date)
                print("✅ Notas com IA geradas e salvas com sucesso.")
            else:
                print("⚠️ Geração de notas com IA foi pulada ou falhou.")
        except Exception as e:
            print(f"❌ Erro na geração de notas: {e}")
            return False
        
        print("\\n✨ WORKFLOW COMPLETO FINALIZADO! ✨")
        return True
    
    def workflow_status_check(self) -> dict:
        """
        Verifica status dos componentes do workflow
        
        Returns:
            dict: Status dos componentes
        """
        status = {
            'config_valid': False,
            'audio_files_available': False,
            'transcriptions_exist': False,
            'api_configured': False,
            'required_files_exist': False
        }
        
        try:
            # Verifica configuração
            self.config.validate_required_files()
            status['config_valid'] = True
            status['required_files_exist'] = True
        except:
            pass
        
        # Verifica arquivos de áudio
        audio_files = list(self.config.AUDIO_OUTPUT_DIR.glob("*.flac"))
        if audio_files:
            status['audio_files_available'] = True
        
        # Verifica transcrições existentes
        transcription_files = list(self.config.TEMP_TRANSCRIPTIONS.glob("*.json"))
        if transcription_files:
            status['transcriptions_exist'] = True
        
        # Verifica configuração da API
        if self.config.GEMINI_API_KEY:
            status['api_configured'] = True
        
        return status
    
    def _process_session_info(self) -> Optional[Tuple[int, date]]:
        """
        Processa informações da sessão (número e data)
        
        Returns:
            Tuple[int, date]: (session_number, session_date) ou None se erro
        """
        # Import local para evitar dependência circular
        from core.session_manager import SessionManager
        
        session_manager = SessionManager(self.config)
        return session_manager.process_chat_log()
    
    def _validate_transcript_content(self, transcript_file: Path) -> bool:
        """
        Valida se arquivo de transcrição tem conteúdo
        
        Args:
            transcript_file: Caminho para arquivo de transcrição
            
        Returns:
            bool: True se arquivo tem conteúdo válido
        """
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if not content:
                return False
            
            # Mostra estatísticas
            char_count = len(content)
            word_count = len(content.split())
            print(f"✅ Transcrições combinadas ({char_count} chars, ~{word_count} palavras)")
            
            return True
            
        except Exception as e:
            print(f"❌ Erro ao verificar arquivo combinado: {e}")
            return False
    
    def get_workflow_summary(self) -> dict:
        """
        Retorna resumo do último workflow executado
        
        Returns:
            dict: Resumo das estatísticas
        """
        # Pega estatísticas dos componentes
        transcriber_stats = self.transcriber.get_transcription_stats()
        
        # Última sessão processada
        output_files = list(self.config.OUTPUT_DIR.glob("Sessão *.md"))
        last_session = None
        if output_files:
            last_session = max(output_files, key=lambda x: x.stat().st_mtime)
        
        return {
            'transcription_stats': transcriber_stats,
            'last_session_file': str(last_session) if last_session else None,
            'total_sessions_processed': len(output_files),
            'workflow_status': self.workflow_status_check()
        }

def create_workflow_manager(config, transcriber, speaker_mapper, audio_processor, gemini_client):
    """Função utilitária para criar instância do workflow manager"""
    return WorkflowManager(config, transcriber, speaker_mapper, audio_processor, gemini_client)