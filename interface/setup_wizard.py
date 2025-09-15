# interface/setup_wizard.py
"""
Assistente de configuração inicial do sistema
"""
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional, List

class SetupWizard:
    """Classe para gerenciar configuração inicial do sistema"""
    
    def __init__(self):
        """Inicializa assistente de configuração"""
        self.available_parties = {
            "1": {
                "name": "Party 01 - Odyssey of the Dragonlords",
                "short": "OOTDL", 
                "description": "Campanha principal de Odyssey of the Dragonlords"
            },
            "2": {
                "name": "Party 02 - Descent into Avernus",
                "short": "DAA",
                "description": "Campanha oficial Baldur's Gate: Descent into Avernus"
            },
            "3": {
                "name": "Party 03 - Custom Campaign", 
                "short": "Custom",
                "description": "Campanha personalizada"
            },
            "4": {
                "name": "One-Shot Sessions",
                "short": "OneShot", 
                "description": "Sessões avulsas e one-shots"
            }
        }
    
    def handle_temp_directory(self, temp_dir: Path):
        """
        Gerencia diretório temporário existente
        
        Args:
            temp_dir: Caminho para diretório temporário
        """
        if temp_dir.exists() and any(temp_dir.iterdir()):
            print("-" * 50)
            print(f"⚠️ ATENÇÃO: Diretório temporário '{temp_dir}' contém arquivos.")
            print("Continuar pode usar arquivos antigos ou causar comportamento inesperado.")
            
            while True:
                choice = input("Deseja remover o diretório temporário existente? [s/n]: ").lower().strip()
                
                if choice in ['s', 'sim', 'y', 'yes']:
                    try:
                        shutil.rmtree(temp_dir)
                        print(f"🗑️ Diretório temporário '{temp_dir}' foi removido.")
                        break
                    except Exception as e:
                        print(f"❌ Erro ao remover diretório temporário: {e}")
                        sys.exit(1)
                
                elif choice in ['n', 'não', 'nao', 'no']:
                    print("👍 Continuando com arquivos temporários existentes.")
                    break
                
                else:
                    print("❌ Escolha inválida. Digite 's' para sim ou 'n' para não.")
            
            print("-" * 50)
    
    def get_language_choice(self) -> str:
        """
        Obtém escolha do idioma
        
        Returns:
            str: Código do idioma ('pt' ou 'en')
        """
        print("\\n🌐 CONFIGURAÇÃO DE IDIOMA")
        print("-" * 30)
        print("Idiomas disponíveis:")
        print("  [pt] Português")
        print("  [en] English")
        
        while True:
            lang = input("\\nQual o idioma da sessão? [pt/en]: ").strip().lower()
            if lang in ["pt", "en"]:
                print(f"✅ Idioma selecionado: {'Português' if lang == 'pt' else 'English'}")
                return lang
            print("❌ Idioma inválido. Digite 'pt' ou 'en'.")
    
    def get_party_choice(self) -> Dict[str, str]:
        """
        Obtém escolha da party/campanha
        
        Returns:
            dict: Informações da party selecionada
        """
        print("\\n🎭 SELEÇÃO DE CAMPANHA")
        print("-" * 30)
        print("Campanhas disponíveis:")
        
        for key, party in self.available_parties.items():
            print(f"  [{key}] {party['name']}")
            print(f"      {party['description']}")
        
        print("  [custom] Digite um nome personalizado")
        
        while True:
            choice = input(f"\\nEscolha a campanha [1-{len(self.available_parties)}/custom]: ").strip()
            
            if choice in self.available_parties:
                selected_party = self.available_parties[choice]
                print(f"✅ Campanha selecionada: {selected_party['name']}")
                return selected_party
            
            elif choice.lower() == 'custom':
                return self._get_custom_party()
            
            else:
                print(f"❌ Escolha inválida. Digite um número entre 1 e {len(self.available_parties)} ou 'custom'.")
    
    def _get_custom_party(self) -> Dict[str, str]:
        """
        Obtém informações de campanha personalizada
        
        Returns:
            dict: Informações da campanha personalizada
        """
        while True:
            name = input("Digite o nome da campanha personalizada: ").strip()
            if name:
                short = input(f"Digite um nome curto (opcional, padrão='{name[:10]}'): ").strip() or name[:10]
                description = input("Digite uma breve descrição (opcional): ").strip() or "Campanha personalizada"
                
                custom_party = {
                    "name": name,
                    "short": short,
                    "description": description
                }
                
                print(f"✅ Campanha personalizada criada: {name}")
                return custom_party
            
            print("❌ Nome não pode estar vazio.")
    
    def choose_summary_template(self) -> Path:
        """
        Permite escolher template de sumário
        
        Returns:
            Path: Caminho para template selecionado
        """
        print("\\n📋 SELEÇÃO DE TEMPLATE")
        print("-" * 30)
        
        # Procura templates disponíveis
        template_locations = [
            Path("config/prompts/summary_templates"),
            Path("prompts"),
            Path("templates"),
        ]
        
        templates = []
        for location in template_locations:
            if location.exists():
                templates.extend(location.glob("summary-*.txt"))
                templates.extend(location.glob("*template*.txt"))
        
        # Remove duplicatas e ordena
        templates = sorted(list(set(templates)))
        
        if not templates:
            print("❌ Nenhum template encontrado!")
            return self._create_default_template()
        
        print("Templates disponíveis:")
        for idx, template in enumerate(templates, 1):
            display_name = template.stem.replace("summary-", "").replace("template-", "")
            print(f"  [{idx}] {display_name} ({template.name})")
        
        while True:
            try:
                choice = input(f"\\nEscolha o template [1-{len(templates)}]: ").strip()
                choice_num = int(choice)
                
                if 1 <= choice_num <= len(templates):
                    selected = templates[choice_num - 1]
                    print(f"✅ Template selecionado: {selected.name}")
                    return selected
                else:
                    print(f"❌ Escolha inválida. Digite um número entre 1 e {len(templates)}.")
            
            except ValueError:
                print(f"❌ Entrada inválida. Digite um número entre 1 e {len(templates)}.")
            
            except KeyboardInterrupt:
                print("\\n👋 Operação cancelada pelo usuário.")
                sys.exit(0)
    
    def _create_default_template(self) -> Path:
        """
        Cria template padrão se nenhum for encontrado
        
        Returns:
            Path: Caminho para template criado
        """
        print("⚠️ Nenhum template encontrado. Criando template padrão...")
        
        templates_dir = Path("config/prompts/summary_templates")
        templates_dir.mkdir(parents=True, exist_ok=True)
        
        default_template = templates_dir / "summary-default.txt"
        
        default_content = '''Você é um assistente que cria resumos detalhados de sessões de RPG.

Analise a transcrição fornecida e crie um resumo extenso e envolvente dos acontecimentos.

Instruções:
1. Escreva em linguagem narrativa, como em um conto
2. Transmita a atmosfera da sessão
3. Destaque momentos importantes (sérios e humorísticos)
4. O resumo deve ter pelo menos 400-500 palavras
5. Capture todos os detalhes relevantes

Gere apenas o resumo, sem título ou comentários adicionais.'''
        
        with open(default_template, 'w', encoding='utf-8') as f:
            f.write(default_content)
        
        print(f"✅ Template padrão criado: {default_template}")
        return default_template
    
    def display_final_configuration(self, language: str, party: Dict, template: Path):
        """
        Exibe configuração final para confirmação
        
        Args:
            language: Idioma selecionado
            party: Informações da party
            template: Template selecionado
        """
        print("\\n📋 CONFIGURAÇÃO FINAL")
        print("=" * 40)
        print(f"🌐 Idioma: {'Português' if language == 'pt' else 'English'}")
        print(f"🎭 Campanha: {party['name']}")
        print(f"📋 Template: {template.name}")
        print("=" * 40)
        
        # Confirma configuração
        while True:
            confirm = input("\\nConfirma esta configuração? [s/n]: ").lower().strip()
            if confirm in ['s', 'sim', 'y', 'yes']:
                print("✅ Configuração confirmada!")
                break
            elif confirm in ['n', 'não', 'nao', 'no']:
                print("❌ Configuração cancelada. Reinicie o programa.")
                sys.exit(0)
            else:
                print("❌ Digite 's' para sim ou 'n' para não.")
    
    def show_setup_complete(self):
        """Mostra mensagem de setup completo"""
        print("\\n" + "🎉" * 20)
        print("✅ CONFIGURAÇÃO INICIAL CONCLUÍDA!")
        print("🚀 Sistema pronto para processar sessões de RPG")
        print("🎉" * 20)

def create_setup_wizard():
    """Função utilitária para criar instância do setup wizard"""
    return SetupWizard()