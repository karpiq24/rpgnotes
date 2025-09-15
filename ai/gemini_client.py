# ai/gemini_client.py
"""
Cliente para interação com a API do Google Gemini - Versão Corrigida
"""
import time
import re
from pathlib import Path
from typing import Tuple, Optional
import google.generativeai as genai
import instructor
from .models import SessionData

class GeminiClient:
    """Cliente para gerar conteúdo usando Google Gemini"""
    
    def __init__(self, config, lang_config: dict = None, summary_template: Path = None):
        """
        Inicializa o cliente Gemini
        
        Args:
            config: Configuração principal
            lang_config: Configuração específica do idioma (opcional)
            summary_template: Template de sumário escolhido (opcional)
        """
        self.config = config
        self.lang_config = lang_config or {}
        self.summary_template = summary_template
        
        # Configura a API
        if config.GEMINI_API_KEY:
            genai.configure(api_key=config.GEMINI_API_KEY)
        
        # Carrega prompts
        self._load_prompts()
    
    def _load_prompts(self):
        """Carrega os prompts necessários"""
        try:
            # Prompt de sumário do template escolhido ou padrão
            if self.summary_template and self.summary_template.exists():
                with open(self.summary_template, 'r', encoding='utf-8') as f:
                    self.summary_prompt = f.read().strip()
            else:
                # Template padrão se não especificado
                self.summary_prompt = self._get_default_summary_prompt()
            
            # Prompt de detalhes
            if self.config.DETAILS_PROMPT_FILE.exists():
                with open(self.config.DETAILS_PROMPT_FILE, 'r', encoding='utf-8') as f:
                    self.details_prompt = f.read().strip()
            else:
                self.details_prompt = self._get_default_details_prompt()
                
        except Exception as e:
            print(f"⚠️ Erro ao carregar prompts: {e}")
            self.summary_prompt = self._get_default_summary_prompt()
            self.details_prompt = self._get_default_details_prompt()
    
    def _get_default_summary_prompt(self) -> str:
        """Retorna prompt padrão para sumário"""
        return """Você é um assistente que cria resumos detalhados de sessões de RPG.

Analise a transcrição fornecida e crie um resumo extenso e envolvente dos acontecimentos.

Instruções:
1. Escreva em linguagem narrativa, como em um conto
2. Transmita a atmosfera da sessão
3. Destaque momentos importantes (sérios e humorísticos)
4. O resumo deve ter pelo menos 400-500 palavras
5. Capture todos os detalhes relevantes

Gere apenas o resumo, sem título ou comentários adicionais."""
    
    def _get_default_details_prompt(self) -> str:
        """Retorna prompt padrão para extração de detalhes"""
        return """Você é um assistente que extrai informações estruturadas de sessões de RPG.

Analise o sumário e a transcrição fornecidos e extraia:
- Título da sessão
- Eventos principais
- NPCs importantes
- Locais visitados
- Itens relevantes 
- Citações memoráveis
- Ganchos para próxima sessão
- Sugestões de imagens
- Sugestões de vídeos

Seja preciso e detalhado."""
    
    def generate_session_notes(self, transcript_file: Path) -> Optional[Tuple[str, SessionData]]:
        """
        Gera notas da sessão usando IA
        
        Args:
            transcript_file: Arquivo de transcrição
            
        Returns:
            Tupla com (sumário, dados_estruturados) ou None se erro
        """
        if not self.config.GEMINI_API_KEY:
            print("❌ GEMINI_API_KEY não configurada. Pulando geração de notas.")
            return None
        
        try:
            # Carrega transcrição
            print("📖 Carregando transcrição...")
            with open(transcript_file, 'r', encoding='utf-8') as f:
                transcript_content = f.read()
            
            if not transcript_content.strip():
                print("❌ Arquivo de transcrição está vazio.")
                return None
            
            print(f"✅ Transcrição carregada: {len(transcript_content)} caracteres")
            
            # Gera sumário detalhado
            print("🤖 Gerando sumário detalhado da sessão...")
            summary = self._generate_summary(transcript_content)
            
            # Aguarda para respeitar rate limits
            print("⏳ Aguardando rate limit da API...")
            time.sleep(10)
            
            # Extrai dados estruturados
            print("📊 Extraindo detalhes estruturados...")
            structured_data = self._extract_structured_details(summary, transcript_content)
            
            print("✅ Notas geradas com sucesso!")
            return summary, structured_data
            
        except Exception as e:
            print(f"❌ Erro na geração de notas: {e}")
            return None
    
    def _generate_summary(self, transcript_content: str) -> str:
        """Gera sumário narrativo da sessão"""
        try:
            summary_model = genai.GenerativeModel(
                model_name=self.config.GEMINI_MODEL_NAME,
                system_instruction=self.summary_prompt,
            )
            
            messages = []
            
            # Adiciona contexto se disponível
            if self.lang_config.get('context_data'):
                messages.append({
                    "role": "user", 
                    "parts": [f"CONTEXTO ADICIONAL DA CAMPANHA:\\n{self.lang_config['context_data']}"]
                })
            
            # Adiciona transcrição
            messages.append({
                "role": "user",
                "parts": [f"TRANSCRIÇÃO DA SESSÃO ATUAL:\\n{transcript_content}"]
            })
            
            response = summary_model.generate_content(
                messages,
                generation_config=genai.GenerationConfig(temperature=0.7),
            )
            
            return response.text
            
        except Exception as e:
            print(f"❌ Erro ao gerar sumário: {e}")
            return f"Erro na geração do sumário: {e}"
    
    def _extract_structured_details(self, summary: str, transcript_content: str) -> SessionData:
        """Extrai dados estruturados da sessão"""
        try:
            client = instructor.from_gemini(
                client=genai.GenerativeModel(
                    model_name=self.config.GEMINI_MODEL_NAME,
                    system_instruction=self.details_prompt,
                ),
                mode=instructor.Mode.GEMINI_JSON,
            )
            
            message_content = (
                f"SUMÁRIO DA SESSÃO (use para gerar título, eventos, NPCs, locais, itens e propostas):\\n{summary}\\n\\n"
                f"TRANSCRIÇÃO COMPLETA (use APENAS para encontrar citações exatas):\\n{transcript_content}"
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
            print(f"❌ Erro na extração de detalhes: {e}")
            # Retorna dados padrão em caso de erro
            return SessionData(
                title="Sessão de RPG",
                events=["Erro na extração de eventos"],
                npcs=["Erro na extração de NPCs"],
                locations=["Erro na extração de locais"],
                items=["Erro na extração de itens"],
                quotes=["Erro na extração de citações"],
                hooks=["Erro na extração de ganchos"],
                images=["Error extracting image prompts"],
                videos=["Error extracting video prompts"]
            )
    
    def save_summary_file(self, session_summary: str, session_data: SessionData, session_number: int, session_date):
        """
        Salva as notas geradas em um arquivo Markdown formatado
        
        Args:
            session_summary: Sumário da sessão
            session_data: Dados estruturados extraídos
            session_number: Número da sessão
            session_date: Data da sessão
        """
        try:
            # Carrega template
            if self.config.TEMPLATE_FILE.exists():
                with open(self.config.TEMPLATE_FILE, "r", encoding='utf-8') as f:
                    template = f.read()
            else:
                template = self._get_default_template()
            
            # Formata dados para o template
            output = template.format(
                number=session_number,
                title=session_data.title,
                date=session_date.strftime("%d.%m.%Y"),
                summary=session_summary,
                events="\\n".join(f"* {event}" for event in session_data.events),
                npcs="\\n".join(f"* {npc}" for npc in session_data.npcs),
                locations="\\n".join(f"* {loc}" for loc in session_data.locations),
                items="\\n".join(f"* {item}" for item in session_data.items),
                quotes="\\n".join(f"* {quote}" for quote in session_data.quotes),
                hooks="\\n".join(f"* {hook}" for hook in session_data.hooks),
                images="\\n".join(f"* `{image}`" for image in session_data.images),
                videos="\\n".join(f"* `{video}`" for video in session_data.videos),
            )
            
            # Nome do arquivo seguro
            safe_title = re.sub(r'[\\\\/*?:"<>|]', "", session_data.title)
            output_file = self.config.OUTPUT_DIR / f"Sessão {session_number} - {safe_title}.md"
            
            # Salva arquivo
            with open(output_file, "w", encoding='utf-8') as f:
                f.write(output)
            
            print(f"📄 Notas da sessão salvas: {output_file.name}")
            
        except Exception as e:
            print(f"❌ Erro ao salvar notas: {e}")
    
    def _get_default_template(self) -> str:
        """Retorna template padrão se não existir arquivo de template"""
        return """# Sessão {number}: {title}

**Data:** {date}

## Resumo

{summary}

## Eventos / Decisões-Chave

{events}

## Citações Memoráveis

{quotes}

## Personagens Não Jogadores (NPCs)

{npcs}

## Localizações

{locations}

## Itens

{items}

## Propostas para a Próxima Sessão (Para o Mestre)

{hooks}

## Propostas de Imagens

{images}

## Propostas de Vídeo

{videos}
"""

def create_gemini_client(config, lang_config=None, summary_template=None):
    """Função utilitária para criar instância do cliente Gemini"""
    return GeminiClient(config, lang_config, summary_template)