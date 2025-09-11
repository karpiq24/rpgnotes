#!/usr/bin/env python3
# main.py - Versão adaptada para seus arquivos
"""
RPG Session Notes Automator - Adaptado para craig.flac.zip e craig.aup.zip
"""
import os
import sys
import glob
import zipfile
import json
import datetime
import time
import shutil
import re
from pathlib import Path

import whisper
import instructor
import google.generativeai as genai
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from tqdm import tqdm
from whisper import load_model


# Load environment variables from a .env file
load_dotenv()

# --- Configuration (loaded from .env file) ---
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
TEMP_DIR = Path(os.getenv("TEMP_DIR", "./temp"))
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", "./downloads"))

# Source directories
CHAT_LOG_SOURCE_DIR = DOWNLOADS_DIR
AUDIO_SOURCE_DIR = DOWNLOADS_DIR

# Configuration files and context
DISCORD_MAPPING_FILE = Path(os.getenv("DISCORD_MAPPING_FILE", "./discord_speaker_mapping.json"))
WHISPER_PROMPT_FILE = Path(os.getenv("WHISPER_PROMPT_FILE", "./prompts/whisper.txt"))
SUMMARY_PROMPT_FILE = Path(os.getenv("SUMMARY_PROMPT_FILE", "./prompts/summary-ootdl.txt"))
DETAILS_PROMPT_FILE = Path(os.getenv("DETAILS_PROMPT_FILE", "./prompts/details.txt"))
TEMPLATE_FILE = Path(os.getenv("TEMPLATE_FILE", "./template.md"))
CONTEXT_DIR = Path(os.getenv("CONTEXT_DIR", "./prompts/pt"))

# API and Model Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-pro")

# Output directories
CHAT_LOG_OUTPUT_DIR = OUTPUT_DIR / "_chat_log"
TRANSCRIPTIONS_OUTPUT_DIR = OUTPUT_DIR / "_transcripts"
AUDIO_OUTPUT_DIR = TEMP_DIR / "audio"
TEMP_TRANSCRIPTIONS = TEMP_DIR / "transcriptions"

# === CONFIGURAÇÃO DE PARTIES ===
AVAILABLE_PARTIES = {
    "1": {
        "name": "Party 01 - Odyssey of the Dragonlords",
        "short": "Party 01",
        "description": "Campanha principal de Odyssey of the Dragonlords"
    },
    "2": {
        "name": "Party 02 - Descending into Avernus", 
        "short": "DAA",
        "description": "Descent into Avernus campaign"
    },
    "3": {
        "name": "Party 03 - Custom Campaign",
        "short": "Party 03", 
        "description": "Campanha customizada"
    },
    "4": {
        "name": "One-Shot Sessions",
        "short": "OneShot",
        "description": "Sessões avulsas e one-shots"
    }
}

def setup_directories():
    """Create all necessary directories if they don't exist."""
    for directory in [
        OUTPUT_DIR, TEMP_DIR, CHAT_LOG_OUTPUT_DIR, AUDIO_OUTPUT_DIR,
        TRANSCRIPTIONS_OUTPUT_DIR, TEMP_TRANSCRIPTIONS, CONTEXT_DIR
    ]:
        directory.mkdir(parents=True, exist_ok=True)

# --- Transcrição de áudio com Whisper ---
def transcribe_audio():
    """
    Transcribe all FLAC files in AUDIO_OUTPUT_DIR using Whisper.
    Saves JSON segment files under TEMP_TRANSCRIPTIONS.
    """
    from whisper import load_model
    import torch

    AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_TRANSCRIPTIONS.mkdir(parents=True, exist_ok=True)

    # Escolhe dispositivo
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Usando dispositivo para transcrição: {device}")

    print("Carregando modelo Whisper...")
    model = load_model("large", device=device)
    print("Modelo carregado.")

    flac_files = sorted(AUDIO_OUTPUT_DIR.glob("*.flac"))
    if not flac_files:
        print("Nenhum .flac para transcrever.")
        return

    for audio in flac_files:
        output_json = TEMP_TRANSCRIPTIONS / f"{audio.stem}.json"
        if output_json.exists():
            print(f"{audio.name} já transcrito, pulando.")
            continue

        print(f"Transcrevendo {audio.name} ...")
        result = model.transcribe(str(audio), language="pt")
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(result["segments"], f, indent=2, ensure_ascii=False)
        print(f"Transcrição salva: {output_json.name}")


# --- Combinação de transcrições ---
def combine_transcriptions(session_number: int) -> Path | None:
    """
    Combines individual JSON transcript files into a single JSON and TXT,
    labels speakers based on DISCORD_MAPPING_FILE, and writes to TRANSCRIPTIONS_OUTPUT_DIR.
    Returns the path to the combined TXT.
    """
    TRANSCRIPTIONS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    combined_json = TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.json"
    combined_txt = TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.txt"

    if combined_txt.exists():
        print(f"Transcrição combinada já existe: {combined_txt.name}")
        return combined_txt

    # Carrega mapeamento Discord -> personagem
    if DISCORD_MAPPING_FILE.exists():
        mapping = json.loads(DISCORD_MAPPING_FILE.read_text(encoding="utf-8"))
    else:
        mapping = {}

    # Agrega todos os segmentos
    segments = []
    for seg_file in sorted(TEMP_TRANSCRIPTIONS.glob("*.json")):
        data = json.loads(seg_file.read_text(encoding="utf-8"))
        # extrai speaker do nome do arquivo
        stem = seg_file.stem
        speaker_key = stem.split("-",1)[-1]
        speaker = mapping.get(speaker_key, speaker_key)
        for seg in data:
            text = seg.get("text","").strip()
            if not text: 
                continue
            seg["speaker"] = speaker
            segments.append(seg)

    # Ordena por tempo de início
    segments.sort(key=lambda s: s["start"])

    # Salva JSON combinado
    with open(combined_json, "w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)
    print(f"JSON combinado salvo: {combined_json.name}")

    # Salva TXT legível
    with open(combined_txt, "w", encoding="utf-8") as f:
        current = None
        for seg in segments:
            if seg["speaker"] != current:
                f.write(f"\n\n[{seg['speaker']}]\n")
                current = seg["speaker"]
            f.write(seg["text"].strip() + " ")

    print(f"TXT combinado salvo: {combined_txt.name}")
    return combined_txt



# --- Helper Functions ---
def get_newest_file(directory: Path, pattern: str) -> Path | None:
    """Finds the newest file matching a pattern in a directory."""
    files = list(directory.glob(pattern))
    return max(files, key=os.path.getmtime) if files else None

def get_summary_templates() -> list[Path]:
    """Obtém lista de templates de sumário disponíveis."""
    possible_locations = [
        Path("config/prompts/summary_templates"),
        Path("prompts"),
        Path("templates"),
    ]
    
    patterns = ["summary-*.txt", "*.txt"]
    
    for location in possible_locations:
        if location.exists():
            for pattern in patterns:
                files = sorted(location.glob(pattern))
                if files:
                    print(f"📁 Encontrados templates em: {location}")
                    return files
    
    print("⚠️ Nenhum template encontrado. Criando template padrão...")
    create_default_templates()
    return get_summary_templates()

def create_default_templates():
    """Cria templates padrão se não existirem."""
    templates_dir = Path("config/prompts/summary_templates")
    templates_dir.mkdir(parents=True, exist_ok=True)
    
    ootdl_template = templates_dir / "summary-ootdl.txt"
    if not ootdl_template.exists():
        default_content = """Você é um assistente que cria resumos detalhados de sessões de RPG.

Analise a transcrição fornecida e crie um resumo extenso e envolvente dos acontecimentos.
Escreva em linguagem narrativa, como em um conto, transmitindo a atmosfera da sessão.
Destaque momentos importantes (sérios e humorísticos).

O resumo deve ter pelo menos 400-500 palavras e capturar todos os detalhes relevantes."""
        
        with open(ootdl_template, 'w', encoding='utf-8') as f:
            f.write(default_content)
        print(f"✅ Template padrão criado: {ootdl_template}")

# --- Main Processing Steps ---
def process_chat_log() -> tuple[int | None, datetime.date | None]:
    """
    Processa log de chat se disponível, senão usa data atual e número sequencial.
    """
    # Tenta encontrar arquivo session*.json
    newest_chat_log = get_newest_file(CHAT_LOG_SOURCE_DIR, "session*.json")
    
    if newest_chat_log:
        print(f"📄 Encontrado chat log: {newest_chat_log.name}")
        match = re.search(r'session(\d+)', newest_chat_log.name)
        if match:
            session_number = int(match.group(1))
            
            # Extrai data se possível
            session_date = None
            try:
                with open(newest_chat_log, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
                date_str = log_data.get("archiveDate")
                if date_str:
                    session_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception as e:
                print(f"⚠️ Aviso: Não foi possível extrair data do chat log: {e}")
            
            return session_number, session_date
    
    # Se não encontrar chat log, gera número sequencial e usa data atual
    print("⚠️ Nenhum arquivo session*.json encontrado.")
    print("📅 Gerando número de sessão baseado na data atual...")
    
    today = datetime.date.today()
    # Usa formato YYYYMMDD como número da sessão
    session_number = int(today.strftime("%Y%m%d"))
    
    print(f"✅ Usando sessão número: {session_number} (baseado na data)")
    print(f"✅ Data da sessão: {today.strftime('%Y-%m-%d')}")
    
    return session_number, today

def find_audio_archive() -> Path | None:
    """
    Procura por arquivos de áudio craig em vários formatos.
    """
    patterns = [
        "craig-*.flac.zip",
        "craig-*.flac",
        "craig-*.aup.zip",
        "*craig*.zip"
    ]
    
    for pattern in patterns:
        files = list(AUDIO_SOURCE_DIR.glob(pattern))
        if files:
            newest = max(files, key=os.path.getmtime)
            print(f"🎵 Encontrado arquivo de áudio: {newest.name}")
            return newest
    
    print("❌ Nenhum arquivo de áudio encontrado nos formatos:")
    for pattern in patterns:
        print(f"   - {pattern}")
    return None

def extract_audio_files():
    """
    Extrai arquivos de áudio de vários formatos (flac.zip, aup.zip, ou diretório).
    """
    if any(AUDIO_OUTPUT_DIR.glob("*.flac")):
        print("✅ Arquivos de áudio já extraídos. Pulando extração.")
        return True
    
    audio_archive = find_audio_archive()
    if not audio_archive:
        return False
    
    try:
        if audio_archive.suffix == '.zip':
            # Extrai arquivo ZIP
            with zipfile.ZipFile(audio_archive, 'r') as zip_ref:
                zip_ref.extractall(AUDIO_OUTPUT_DIR)
            print(f"✅ Extraído arquivo ZIP: {audio_archive.name}")
            
            # Se extraiu uma estrutura de diretório (como do aup.zip), encontra os FLACs
            flac_files = list(AUDIO_OUTPUT_DIR.rglob("*.flac"))
            if flac_files:
                # Move todos os FLAC para o diretório raiz
                for flac_file in flac_files:
                    if flac_file.parent != AUDIO_OUTPUT_DIR:
                        new_path = AUDIO_OUTPUT_DIR / flac_file.name
                        shutil.move(str(flac_file), str(new_path))
                        print(f"📁 Movido: {flac_file.name}")
                
                # Limpa diretórios vazios
                for item in AUDIO_OUTPUT_DIR.iterdir():
                    if item.is_dir():
                        try:
                            item.rmdir()
                        except OSError:
                            # Diretório não vazio, remove recursivamente
                            shutil.rmtree(item)
        
        elif audio_archive.is_dir():
            # Copia arquivos FLAC de um diretório
            flac_files = list(audio_archive.glob("*.flac"))
            for flac_file in flac_files:
                shutil.copy2(flac_file, AUDIO_OUTPUT_DIR / flac_file.name)
            print(f"✅ Copiados {len(flac_files)} arquivos FLAC do diretório")
        
        # Remove arquivos não-FLAC
        for item in AUDIO_OUTPUT_DIR.iterdir():
            if item.is_file() and item.suffix != ".flac":
                os.remove(item)
                print(f"🗑️ Removido arquivo não-FLAC: {item.name}")
        
        # Lista arquivos FLAC encontrados
        flac_files = list(AUDIO_OUTPUT_DIR.glob("*.flac"))
        print(f"✅ Total de arquivos FLAC prontos: {len(flac_files)}")
        for flac in sorted(flac_files):
            print(f"   🎵 {flac.name}")
        
        return len(flac_files) > 0
        
    except Exception as e:
        print(f"❌ Erro ao extrair áudio: {e}")
        return False

def load_context_files(context_dir: Path) -> str:
    """Carrega arquivos de contexto."""
    context_data = ""
    if context_dir.exists():
        file_patterns = ["*.txt", "*.md"]
        all_files = set()
        for pattern in file_patterns:
            all_files.update(context_dir.glob(pattern))
        
        for file_path in sorted(list(all_files)):
            try:
                with open(file_path, "r", encoding='utf-8') as f:
                    context_data += f"--- CONTEXT FROM {file_path.name} ---\n{f.read()}\n\n"
            except Exception as e:
                print(f"Error reading context file {file_path}: {e}")
    return context_data

# === INTERFACE FUNCTIONS ===
def handle_temp_directory():
    """Gerencia diretório temporário existente."""
    if TEMP_DIR.exists() and any(TEMP_DIR.iterdir()):
        print("-" * 50)
        print(f"⚠️ Warning: Temporary directory '{TEMP_DIR}' already contains files.")
        print("Continuing may use old files or cause unexpected behavior.")
        
        while True:
            choice = input("Do you want to delete the existing temporary directory? [y/n]: ").lower().strip()
            if choice in ['y', 'yes']:
                try:
                    shutil.rmtree(TEMP_DIR)
                    print(f"🗑️ Temporary directory '{TEMP_DIR}' has been removed.")
                    break
                except Exception as e:
                    print(f"❌ Error removing temporary directory: {e}")
                    sys.exit(1)
            elif choice in ['n', 'no']:
                print("👍 Continuing with existing temporary files.")
                break
            else:
                print("Invalid choice. Please enter 'y' or 'n'.")
        print("-" * 50)

def get_language_choice() -> str:
    """Obtém escolha do idioma."""
    while True:
        lang = input("Qual o idioma da sessão? [en/pt]: ").strip().lower()
        if lang in ["en", "pt"]:
            return lang
        print("❌ Idioma inválido. Digite 'en' ou 'pt'.")

def get_party_choice() -> dict:
    """Obtém escolha da party com lista de opções."""
    print("\n🎭 Parties disponíveis:")
    for key, party in AVAILABLE_PARTIES.items():
        print(f"  [{key}] {party['name']}")
        print(f"      {party['description']}")
    print(f"  [custom] Digite um nome personalizado")
    
    while True:
        choice = input(f"\nEscolha a party [1-{len(AVAILABLE_PARTIES)}/custom]: ").strip().lower()
        
        if choice in AVAILABLE_PARTIES:
            selected_party = AVAILABLE_PARTIES[choice]
            print(f"✅ Party selecionada: {selected_party['name']}")
            return selected_party
        elif choice == 'custom':
            while True:
                custom_name = input("Digite o nome da party personalizada: ").strip()
                if custom_name:
                    return {
                        "name": custom_name,
                        "short": custom_name,
                        "description": "Party personalizada"
                    }
                print("❌ Nome não pode estar vazio.")
        else:
            print(f"❌ Escolha inválida. Digite um número entre 1 e {len(AVAILABLE_PARTIES)} ou 'custom'.")

def choose_summary_template() -> Path:
    """Permite escolher template de sumário."""
    summary_files = get_summary_templates()
    
    if not summary_files:
        print("❌ Erro: Nenhum template de sumário encontrado!")
        sys.exit(1)
    
    print("\n📋 Sumários disponíveis:")
    for idx, sf in enumerate(summary_files):
        display_name = sf.stem.replace("summary-", "")
        print(f"  [{idx+1}] {display_name} ({sf.name})")
    
    while True:
        try:
            choice = input(f"Escolha o sumário [1-{len(summary_files)}]: ").strip()
            choice_num = int(choice)
            if 1 <= choice_num <= len(summary_files):
                selected = summary_files[choice_num - 1]
                print(f"✅ Template selecionado: {selected.name}")
                return selected
            else:
                print(f"❌ Escolha inválida. Digite um número entre 1 e {len(summary_files)}.")
        except ValueError:
            print(f"❌ Entrada inválida. Digite um número entre 1 e {len(summary_files)}.")
        except KeyboardInterrupt:
            print("\n👋 Operação cancelada pelo usuário.")
            sys.exit(0)

def display_main_menu() -> str:
    """Exibe menu principal e retorna escolha do usuário."""
    print("\n" + "="*50)
    print("🚀 D&D Session Processing Workflow 🚀")
    print("="*50)
    print("Escolha uma opção:")
    print(" [1] Workflow Completo (Transcrever → Gerar Notas com IA)")
    print(" [2] Apenas Transcrição (Gerar apenas arquivo de transcrição)")
    print(" [3] Sair")
    print("="*50)
    
    while True:
        choice = input("Digite sua escolha [1-3]: ").strip()
        if choice in ['1', '2', '3']:
            return choice
        print("❌ Escolha inválida. Digite um número de 1 a 3.")

# === WORKFLOW SIMPLIFICADO (placeholder) ===
def run_transcription_workflow():
    """Executa workflow de transcrição."""
    print("\n[Passo 1/4] Processando informações da sessão...")
    session_number, session_date = process_chat_log()
    
    if not session_number:
        print("❌ Erro ao determinar número da sessão.")
        return None
    
    print(f"✅ Sessão: {session_number}")
    print(f"✅ Data: {session_date.strftime('%Y-%m-%d')}")
    
    print("\n[Passo 2/4] Extraindo arquivos de áudio...")
    if not extract_audio_files():
        print("❌ Erro ao extrair arquivos de áudio.")
        return None
    
    print("✅ Arquivos de áudio prontos para transcrição!")
    
    print("\n[Passo 3/4] Transcrição de áudio...")
    transcribe_audio()  # Função que carrega modelo Whisper e gera .json
    print("✅ Transcrição concluída.")
    
    print("\n[Passo 4/4] Combinação de transcrições...")  
    print("[Passo 4/4] Combinação de transcrições...")
    transcript_file = combine_transcriptions(session_number)
    if transcript_file:
        print("✅ Transcrições combinadas.")
    else:
        print("❌ Erro ao combinar transcrições.")
    
    print("\n✨ Workflow de transcrição preparado! ✨")
    return session_number, session_date

def run_full_workflow():
    """Executa workflow completo."""
    result = run_transcription_workflow()
    if not result:
        return
    
    session_number, session_date = result
    
    print("\n[Passo 5/5] Geração de notas com IA...")
    print("⚠️ Geração com IA será implementada após a transcrição.")
    
    print("\n✨ Workflow completo preparado! ✨")

def main():
    """Função principal."""
    print("🚀 RPG Session Notes Automator 🚀")
    print("=" * 50)
    
    try:
        # Setup inicial
        handle_temp_directory()
        setup_directories()
        
        # Coleta configurações da sessão
        language = get_language_choice()
        party_info = get_party_choice()
        summary_template = choose_summary_template()
        
        print(f"\n📋 Configuração:")
        print(f"   Idioma: {language}")
        print(f"   Party: {party_info['name']}")
        print(f"   Template: {summary_template.name}")
        
        # Configuração global
        global SUMMARY_PROMPT_FILE, CONTEXT_DIR
        SUMMARY_PROMPT_FILE = summary_template
        CONTEXT_DIR = Path("prompts") / language
        
        # Loop principal do menu
        while True:
            choice = display_main_menu()
            
            if choice == '1':
                print("\n🎯 Iniciando Workflow Completo...")
                run_full_workflow()
                
            elif choice == '2':
                print("\n📝 Iniciando Workflow de Transcrição...")
                run_transcription_workflow()
                
            elif choice == '3':
                print("\n👋 Encerrando aplicação. Até logo!")
                break
            
            print("\n🔄 Retornando ao menu principal...")
            input("Pressione Enter para continuar...")
    
    except KeyboardInterrupt:
        print("\n\n⚠️ Operação cancelada pelo usuário.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()