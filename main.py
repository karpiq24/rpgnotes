#!/usr/bin/env python3
"""
RPG Session Notes Automator - Versão Modularizada Corrigida
Arquivo principal reformulado para usar arquivos auxiliares
"""

# Imports de módulos do sistema
from core.config import Config
from core.workflows import WorkflowManager
from audio.transcriber import WhisperTranscriber
from audio.speaker_mapping import SpeakerMapper
from audio.processor import AudioProcessor
from ai.gemini_client import GeminiClient
from interface.menu import MenuInterface
from interface.setup_wizard import SetupWizard

# Imports padrão
import sys
from pathlib import Path

class RPGNotesAutomator:
    """Classe principal do automatizador de notas de RPG"""
    
    def __init__(self):
        """Inicializa o automatizador"""
        print("🚀 RPG Session Notes Automator 🚀")
        print("=" * 50)
        
        # Carrega configurações
        self.config = Config()
        self.config.validate_required_files()
        self.config.setup_directories()
        
        # Inicializa componentes
        self._initialize_components()
        
        # Interface de usuário
        self.menu = MenuInterface()
        self.setup_wizard = SetupWizard()
    
    def _initialize_components(self):
        """Inicializa todos os componentes do sistema"""
        try:
            # Componentes de áudio
            self.audio_processor = AudioProcessor(self.config)
            self.transcriber = WhisperTranscriber(self.config)
            self.speaker_mapper = SpeakerMapper(self.config)
            
            # Componente de IA (corrigido - sem argumentos obrigatórios)
            self.gemini_client = GeminiClient(self.config)
            
            # Gerenciador de workflows
            self.workflow_manager = WorkflowManager(
                self.config,
                self.transcriber,
                self.speaker_mapper,
                self.audio_processor,
                self.gemini_client
            )
            
            print("✅ Todos os componentes inicializados com sucesso")
            
        except Exception as e:
            print(f"❌ Erro ao inicializar componentes: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    def run_setup(self):
        """Executa configuração inicial"""
        print("\\n🔧 CONFIGURAÇÃO INICIAL")
        print("-" * 30)
        
        # Gerencia diretório temporário
        self.setup_wizard.handle_temp_directory(self.config.TEMP_DIR)
        
        # Configurações da sessão
        language = self.setup_wizard.get_language_choice()
        party_info = self.setup_wizard.get_party_choice()
        summary_template = self.setup_wizard.choose_summary_template()
        
        # Atualiza configuração do cliente Gemini
        lang_config = {'language': language, 'party': party_info}
        self.gemini_client = GeminiClient(self.config, lang_config, summary_template)
        
        # Atualiza workflow manager com novo cliente
        self.workflow_manager.gemini_client = self.gemini_client
        
        # Atualiza configuração global
        self.config.SUMMARY_PROMPT_FILE = summary_template
        self.config.CONTEXT_DIR = Path("prompts") / language
        
        # Mostra configuração final
        print(f"\\n📋 CONFIGURAÇÃO FINAL:")
        print(f" • Idioma: {language}")
        print(f" • Party: {party_info['name']}")
        print(f" • Template: {summary_template.name}")
        
        return {
            'language': language,
            'party': party_info,
            'template': summary_template
        }
    
    def run_main_loop(self):
        """Executa loop principal do programa"""
        try:
            # Configuração inicial
            setup_config = self.run_setup()
            
            # Loop do menu principal
            while True:
                choice = self.menu.display_main_menu()
                
                if choice == '1':
                    # Workflow completo
                    print("\\n🎯 INICIANDO WORKFLOW COMPLETO...")
                    success = self.workflow_manager.run_full_workflow()
                    
                    if success:
                        self._show_completion_summary()
                    else:
                        print("❌ Workflow completado com erros.")
                
                elif choice == '2':
                    # Apenas transcrição
                    print("\\n📝 INICIANDO WORKFLOW DE TRANSCRIÇÃO...")
                    result = self.workflow_manager.run_transcription_workflow()
                    
                    if result:
                        session_number, session_date = result
                        print(f"✅ Transcrição concluída para sessão {session_number}")
                        self._show_transcription_summary(session_number)
                    else:
                        print("❌ Transcrição falhou.")
                
                elif choice == '3':
                    # Sair
                    print("\\n👋 Encerrando aplicação. Até logo!")
                    break
                
                # Pausa antes de retornar ao menu
                self._wait_for_continue()
        
        except KeyboardInterrupt:
            print("\\n\\n⚠️ Operação cancelada pelo usuário.")
            sys.exit(0)
        
        except Exception as e:
            print(f"\\n❌ Erro inesperado: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    def _show_completion_summary(self):
        """Mostra resumo após conclusão do workflow completo"""
        summary = self.workflow_manager.get_workflow_summary()
        
        print("\\n📊 RESUMO DO WORKFLOW:")
        print("-" * 30)
        
        # Estatísticas de transcrição
        if 'transcription_stats' in summary:
            stats = summary['transcription_stats']
            print(f"🎙️ Arquivos processados: {stats.get('total_files', 0)}")
            print(f"📝 Segmentos transcritos: {stats.get('total_segments', 0)}")
            print(f"⏱️ Duração estimada: {stats.get('estimated_duration_minutes', 0):.1f} min")
            print(f"🖥️ Dispositivo usado: {stats.get('device_used', 'N/A')}")
        
        # Arquivo gerado
        if summary.get('last_session_file'):
            print(f"📄 Notas salvas em: {Path(summary['last_session_file']).name}")
        
        print(f"🎯 Total de sessões processadas: {summary.get('total_sessions_processed', 0)}")
    
    def _show_transcription_summary(self, session_number: int):
        """
        Mostra resumo após transcrição
        
        Args:
            session_number: Número da sessão processada
        """
        print("\\n📊 RESUMO DA TRANSCRIÇÃO:")
        print("-" * 30)
        
        # Estatísticas do speaker mapper
        speaker_stats = self.speaker_mapper.get_speaker_stats(session_number)
        
        if speaker_stats:
            print("👥 Estatísticas por Speaker:")
            for speaker, stats in speaker_stats.items():
                duration_min = stats['total_duration'] / 60
                print(f"  • {speaker}: {stats['segments']} segmentos, "
                      f"{duration_min:.1f}min, {stats['word_count']} palavras")
        
        # Arquivos gerados
        transcript_file = self.config.TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.txt"
        if transcript_file.exists():
            print(f"📄 Transcrição salva em: {transcript_file.name}")
    
    def _wait_for_continue(self):
        """Aguarda usuário pressionar Enter"""
        print("\\n🔄 Retornando ao menu principal...")
        input("Pressione Enter para continuar...")

def main():
    """Função principal"""
    try:
        # Cria e executa automatizador
        automator = RPGNotesAutomator()
        automator.run_main_loop()
        
    except Exception as e:
        print(f"❌ Erro fatal ao inicializar: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()