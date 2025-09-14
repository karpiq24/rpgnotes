# interface/menu.py
"""
Interface de menu principal do sistema
"""
from typing import Optional

class MenuInterface:
    """Classe para gerenciar interface de menu principal"""
    
    def __init__(self):
        """Inicializa interface de menu"""
        pass
    
    def display_main_menu(self) -> str:
        """
        Exibe menu principal e retorna escolha do usuário
        
        Returns:
            str: Escolha do usuário ('1', '2', '3')
        """
        print("\\n" + "=" * 50)
        print("🚀 RPG Session Notes Automator 🚀")
        print("=" * 50)
        print("Escolha uma opção:")
        print(" [1] Workflow Completo (Transcrever → Gerar Notas com IA)")
        print(" [2] Apenas Transcrição (Gerar apenas arquivo de transcrição)")
        print(" [3] Sair")
        print("=" * 50)
        
        return self._get_user_choice(['1', '2', '3'])
    
    def _get_user_choice(self, valid_choices: list) -> str:
        """
        Obtém escolha válida do usuário
        
        Args:
            valid_choices: Lista de escolhas válidas
            
        Returns:
            str: Escolha validada do usuário
        """
        while True:
            try:
                choice = input(f"Digite sua escolha [{'/'.join(valid_choices)}]: ").strip()
                if choice in valid_choices:
                    return choice
                print(f"❌ Escolha inválida. Digite um dos valores: {', '.join(valid_choices)}")
            except KeyboardInterrupt:
                print("\\n👋 Operação cancelada pelo usuário.")
                return '3'  # Retorna opção de saída
            except Exception as e:
                print(f"❌ Erro na entrada: {e}")
    
    def show_workflow_progress(self, step: int, total: int, description: str):
        """
        Mostra progresso do workflow
        
        Args:
            step: Passo atual
            total: Total de passos
            description: Descrição do passo atual
        """
        print(f"\\n[Passo {step}/{total}] {description}")
        
        # Barra de progresso simples
        progress = "█" * step + "░" * (total - step)
        percentage = (step / total) * 100
        print(f"Progresso: [{progress}] {percentage:.0f}%")
    
    def display_error_menu(self, error_message: str) -> str:
        """
        Exibe menu de erro com opções de recuperação
        
        Args:
            error_message: Mensagem de erro a exibir
            
        Returns:
            str: Escolha do usuário
        """
        print("\\n" + "=" * 50)
        print("❌ ERRO DETECTADO")
        print("=" * 50)
        print(f"Erro: {error_message}")
        print("\\nOpções de recuperação:")
        print(" [1] Tentar novamente")
        print(" [2] Voltar ao menu principal") 
        print(" [3] Sair")
        print("=" * 50)
        
        return self._get_user_choice(['1', '2', '3'])
    
    def display_success_message(self, message: str, details: dict = None):
        """
        Exibe mensagem de sucesso com detalhes opcionais
        
        Args:
            message: Mensagem principal de sucesso
            details: Detalhes adicionais (opcional)
        """
        print("\\n" + "✅" * 20)
        print(f"🎉 {message}")
        
        if details:
            print("\\n📊 Detalhes:")
            for key, value in details.items():
                print(f"   • {key}: {value}")
        
        print("✅" * 20)
    
    def confirm_action(self, action: str) -> bool:
        """
        Confirma uma ação com o usuário
        
        Args:
            action: Descrição da ação a confirmar
            
        Returns:
            bool: True se usuário confirmou
        """
        print(f"\\n⚠️ Confirmação necessária:")
        print(f"   {action}")
        
        choice = self._get_user_choice(['s', 'n', 'y', 'yes', 'no', 'sim'])
        return choice.lower() in ['s', 'y', 'yes', 'sim']
    
    def display_workflow_summary(self, summary_data: dict):
        """
        Exibe resumo do workflow executado
        
        Args:
            summary_data: Dados do resumo do workflow
        """
        print("\\n📋 RESUMO DO WORKFLOW")
        print("=" * 30)
        
        if 'transcription_stats' in summary_data:
            stats = summary_data['transcription_stats']
            print(f"🎙️ Arquivos processados: {stats.get('total_files', 0)}")
            print(f"📝 Segmentos transcritos: {stats.get('total_segments', 0)}")
            print(f"⏱️ Duração estimada: {stats.get('estimated_duration_minutes', 0):.1f} min")
            print(f"🖥️ Dispositivo usado: {stats.get('device_used', 'N/A')}")
        
        if summary_data.get('last_session_file'):
            from pathlib import Path
            print(f"📄 Arquivo gerado: {Path(summary_data['last_session_file']).name}")
        
        print(f"🎯 Total de sessões: {summary_data.get('total_sessions_processed', 0)}")
    
    def wait_for_continue(self):
        """Aguarda usuário pressionar Enter para continuar"""
        print("\\n🔄 Retornando ao menu principal...")
        try:
            input("Pressione Enter para continuar...")
        except KeyboardInterrupt:
            print("\\n👋 Voltando ao menu...")

def create_menu_interface():
    """Função utilitária para criar instância do menu"""
    return MenuInterface()