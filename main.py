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

# Load environment variables from a .env file
load_dotenv()

# --- Configuration (loaded from .env file) ---
# Main directories
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR"))
TEMP_DIR = Path(os.getenv("TEMP_DIR"))
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR"))

# Source directories are now the same
CHAT_LOG_SOURCE_DIR = DOWNLOADS_DIR
AUDIO_SOURCE_DIR = DOWNLOADS_DIR

# Configuration files and context
DISCORD_MAPPING_FILE = Path(os.getenv("DISCORD_MAPPING_FILE"))
WHISPER_PROMPT_FILE = Path(os.getenv("WHISPER_PROMPT_FILE"))
SUMMARY_PROMPT_FILE = Path(os.getenv("SUMMARY_PROMPT_FILE"))
DETAILS_PROMPT_FILE = Path(os.getenv("DETAILS_PROMPT_FILE"))
TEMPLATE_FILE = Path(os.getenv("TEMPLATE_FILE"))
CONTEXT_DIR = Path(os.getenv("CONTEXT_DIR"))

# API and Model Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME")

# --- Setup Directories ---
# These are subdirectories for organized output
CHAT_LOG_OUTPUT_DIR = OUTPUT_DIR / "_chat_log"
TRANSCRIPTIONS_OUTPUT_DIR = OUTPUT_DIR / "_transcripts"
AUDIO_OUTPUT_DIR = TEMP_DIR / "audio"
TEMP_TRANSCRIPTIONS = TEMP_DIR / "transcriptions"

def setup_directories():
    """Create all necessary directories if they don't exist."""
    for directory in [
        OUTPUT_DIR, TEMP_DIR, CHAT_LOG_OUTPUT_DIR, AUDIO_OUTPUT_DIR,
        TRANSCRIPTIONS_OUTPUT_DIR, TEMP_TRANSCRIPTIONS, CONTEXT_DIR
    ]:
        directory.mkdir(parents=True, exist_ok=True)

# --- Helper Functions ---

def get_newest_file(directory: Path, pattern: str) -> Path | None:
    """Finds the newest file matching a pattern in a directory."""
    files = list(directory.glob(pattern))
    return max(files, key=os.path.getmtime) if files else None

def prettify_json(filepath: Path) -> str | None:
    """Reads, prettifies, and returns JSON data from a file as a string."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        return json.dumps(json_data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as e:
        print(f"Error processing JSON in {filepath}: {e}")
        return None

def load_context_files(context_dir: Path) -> str:
    """Loads all text and markdown files from the context directory into a single string."""
    context_data = ""
    if context_dir.exists():
        # Look for both .txt and .md files
        file_patterns = ["*.txt", "*.md"]
        all_files = set()
        for pattern in file_patterns:
            all_files.update(context_dir.glob(pattern))
            
        for file_path in sorted(list(all_files)): # Sort to maintain a consistent order
            try:
                with open(file_path, "r", encoding='utf-8') as f:
                    context_data += f"--- CONTEXT FROM {file_path.name} ---\n{f.read()}\n\n"
            except Exception as e:
                print(f"Error reading context file {file_path}: {e}")
    return context_data

# --- Main Processing Steps ---

def process_chat_log() -> tuple[int | None, datetime.date | None]:
    """
    Finds the newest session chat log, extracts the session number and date,
    prettifies it, and saves it to the chat log output directory.
    """
    newest_chat_log = get_newest_file(CHAT_LOG_SOURCE_DIR, "session*.json")
    if not newest_chat_log:
        print("No session chat log found (e.g., 'session53.json').")
        return None, None

    match = re.search(r'session(\d+)', newest_chat_log.name)
    if not match:
        print(f"Could not extract session number from filename: {newest_chat_log.name}")
        return None, None
    session_number = int(match.group(1))

    session_date = None
    try:
        with open(newest_chat_log, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
            date_str = log_data.get("archiveDate")
            if date_str:
                session_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Warning: Could not extract date from chat log {newest_chat_log.name}: {e}.")

    output_filepath = CHAT_LOG_OUTPUT_DIR / f"session{session_number}.json"
    if output_filepath.exists():
        print(f"Chat log for session {session_number} already exists. Skipping processing.")
        return session_number, session_date

    prettified_json_string = prettify_json(newest_chat_log)
    if not prettified_json_string:
        return session_number, session_date

    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write(prettified_json_string)
    print(f"Prettified chat log saved to: {output_filepath}")

    return session_number, session_date


def unzip_audio():
    """Unzips the newest FLAC zip file to the audio output directory."""
    if any(AUDIO_OUTPUT_DIR.glob("*.flac")):
        print("Audio files already exist. Skipping unzip.")
        return

    newest_zip = get_newest_file(AUDIO_SOURCE_DIR, "craig-*.flac.zip")
    if not newest_zip:
        print("No matching audio zip file (craig-*.flac.zip) found.")
        return

    try:
        with zipfile.ZipFile(newest_zip, 'r') as zip_ref:
            zip_ref.extractall(AUDIO_OUTPUT_DIR)
        print(f"Extracted audio to: {AUDIO_OUTPUT_DIR}")

        # Clean up non-FLAC files from the extraction directory
        for item in AUDIO_OUTPUT_DIR.iterdir():
            if item.is_file() and item.suffix != ".flac":
                os.remove(item)
                print(f"Deleted non-FLAC file: {item.name}")

        os.remove(newest_zip)
        print(f"Deleted source zip file: {newest_zip.name}")

    except zipfile.BadZipFile:
        print(f"Error: {newest_zip.name} is not a valid zip file.")
    except Exception as e:
        print(f"An error occurred during unzipping: {e}")

class _CustomProgressBar(tqdm):
    """Custom progress bar to display elapsed and estimated remaining time."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current = self.n
        self._start_time = time.time()
        self._last_update_time = self._start_time
        self._iteration_times = []

    def print_in_place(self, text):
        sys.stdout.write("\r" + text)
        sys.stdout.flush()

    def update(self, n):
        super().update(n)
        self._current += n

        current_time = time.time()
        elapsed_time = current_time - self._start_time
        iteration_time = current_time - self._last_update_time
        self._iteration_times.append(iteration_time / n)
        average_iteration_time = sum(self._iteration_times) / len(self._iteration_times)
        remaining_items = self.total - self._current
        estimated_remaining_time = remaining_items * average_iteration_time

        elapsed_time_str = time.strftime("%H:%M:%S", time.gmtime(elapsed_time))
        remaining_time_str = time.strftime("%H:%M:%S", time.gmtime(estimated_remaining_time))

        percentage = (self._current / self.total) * 100
        self.print_in_place(f"Progress: {percentage:.2f}% - Elapsed: {elapsed_time_str} - ETA: {remaining_time_str}")

        self._last_update_time = current_time


def transcribe_audio():
    """
    Transcribes all FLAC audio files in the audio directory using Whisper.
    Skips files that have already been transcribed.
    """
    model_name = "large"
    device = "cuda" # 'cuda' for NVIDIA GPUs, 'cpu' for CPU

    # Check if all audio files are already transcribed before loading the model
    audio_files = sorted(AUDIO_OUTPUT_DIR.glob("*.flac"), key=os.path.getsize)
    files_to_transcribe = [
        f for f in audio_files
        if not (TEMP_TRANSCRIPTIONS / f"{f.stem}.json").exists()
    ]

    if not files_to_transcribe:
        print("All audio files already transcribed. Skipping.")
        return

    # Inject custom progress bar into Whisper
    transcribe_module = sys.modules['whisper.transcribe']
    transcribe_module.tqdm.tqdm = _CustomProgressBar

    try:
        model = whisper.load_model(model_name, device=device, download_root="./models/")
    except Exception as e:
        print(f"Error loading Whisper model: {e}")
        print("Ensure you have a compatible CUDA version or change device to 'cpu'.")
        return

    with open(WHISPER_PROMPT_FILE, "r", encoding='utf-8') as f:
        initial_prompt = f.read().strip()

    for audio_file in tqdm(files_to_transcribe, desc="Transcribing Audio"):
        json_output_path = TEMP_TRANSCRIPTIONS / f"{audio_file.stem}.json"
        print(f"Transcribing {audio_file.name}...")
        try:
            result = model.transcribe(
                str(audio_file),
                language="pl",
                initial_prompt=initial_prompt
            )
            with open(json_output_path, "w", encoding='utf-8') as f:
                json.dump(result["segments"], f, indent=2, ensure_ascii=False)
            print(f"\nTranscription of '{audio_file.name}' saved.")
        except Exception as e:
            print(f"Error transcribing '{audio_file.name}': {e}")


def combine_transcriptions(session_number: int) -> Path | None:
    """
    Combines individual JSON transcriptions into a single JSON and a single TXT file.
    Assigns speaker labels based on the mapping file.
    """
    combined_json_path = TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.json"
    combined_txt_path = TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.txt"

    if combined_json_path.exists() and combined_txt_path.exists():
        print(f"Combined transcriptions for session {session_number} already exist. Skipping.")
        return combined_txt_path

    try:
        with open(DISCORD_MAPPING_FILE, "r", encoding='utf-8') as f:
            discord_character_mapping = json.load(f)
    except FileNotFoundError:
        print(f"Warning: Mapping file '{DISCORD_MAPPING_FILE}' not found. Using raw Discord usernames.")
        discord_character_mapping = {}

    all_segments = []
    json_files = sorted(list(TEMP_TRANSCRIPTIONS.glob("*.json")))

    for json_file in json_files:
        try:
            # Assumes filename format like "123456-DiscordUser_1234.flac"
            discord_user = json_file.stem.split("-", 1)[1].lstrip("_").split("_")[0]
            speaker = discord_character_mapping.get(discord_user, discord_user)
        except IndexError:
            print(f"Warning: Could not extract speaker from {json_file.name}. Using filename stem.")
            speaker = json_file.stem

        with open(json_file, "r", encoding='utf-8') as f:
            segments = json.load(f)
            for segment in segments:
                # Filter out low-confidence or junk segments
                text = segment['text'].strip()
                if segment.get("no_speech_prob", 0.0) > 0.3 or not text:
                    continue
                if text in ["...", "... ...", "Dziękuję.", "Dzień dobry.", "Ale..."]:
                    continue
                segment["speaker"] = speaker
                all_segments.append(segment)

    # Sort all collected segments by their start time
    all_segments.sort(key=lambda x: x["start"])

    # Save the combined, sorted JSON
    with open(combined_json_path, "w", encoding='utf-8') as f:
        json.dump(all_segments, f, indent=2, ensure_ascii=False)

    # Save the human-readable TXT transcript
    with open(combined_txt_path, "w", encoding='utf-8') as f:
        current_speaker = None
        for segment in all_segments:
            if segment["speaker"] != current_speaker:
                f.write(f"\n\n[{segment['speaker']}]\n")
                current_speaker = segment["speaker"]
            f.write(segment["text"].strip() + " ")

    print(f"Combined transcription saved to {combined_txt_path}")
    return combined_txt_path

# --- AI Generation and Note Creation ---

class SessionData(BaseModel):
    """Pydantic model for structuring data extracted by Gemini."""
    title: str = Field(description="Tytuł sesji. Powinien być krótki, ale opisowy i chwytliwy.")
    events: list[str] = Field(description="Krótka, punktowa lista najważniejszych wydarzeń lub decyzji, które miały miejsce.")
    npcs: list[str] = Field(description="Lista najważniejszych postaci niezależnych (NPC), które pojawiły się lub odegrały kluczową rolę.")
    locations: list[str] = Field(description="Lista najważniejszych odwiedzonych lokacji.")
    items: list[str] = Field(description="Lista najważniejszych zdobytych lub użytych przedmiotów.")
    quotes: list[str] = Field(description="Lista 5-7 najbardziej pamiętnych, zabawnych lub ważnych cytatów z sesji, wraz z informacją, kto je wypowiedział. Np. 'Arevon: 'Coś tu jest nie tak.'.")
    hooks: list[str] = Field(description="Lista 3-4 propozycji lub 'zajawek' na następną sesję, skierowanych do Mistrza Gry. Każda powinna być intrygującym pytaniem lub sytuacją wynikającą z wydarzeń tej sesji.")
    images: list[str] = Field(
        description="""Lista 10 promptów do użycia w generatorach obrazów AI, **napisanych w języku angielskim**.
                       Każdy prompt powinien zaczynać się od słowa 'Draw'.
                       Unikaj nazw własnych postaci, zamiast tego opisz ich wygląd i akcję.
                       Stosuj różnorodne style artystyczne (np. 'oil painting', 'fantasy art', 'cinematic')."""
    )
    videos: list[str] = Field(
        description="""Lista 10 szczegółowych promptów do generowania **wideo**, **napisanych w języku angielskim**.
                       Każdy prompt powinien opisywać krótką, dynamiczną scenę (3-5 sekund), zawierającą ruch kamery, akcje postaci i zmiany w otoczeniu."""
    )

def generate_session_notes(transcript_file: Path) -> tuple[str, str, SessionData] | None:
    """Generates a detailed summary and structured data using the Gemini API."""
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set in .env file. Skipping note generation.")
        return None
        
    genai.configure(api_key=GEMINI_API_KEY)
    
    with open(transcript_file, "r", encoding='utf-8') as f:
        transcript_content = f.read()

    # --- Step 1: Generate Detailed Summary ---
    with open(SUMMARY_PROMPT_FILE, "r", encoding='utf-8') as f:
        summary_prompt = f.read()

    summary_model = genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=summary_prompt,
    )
    
    summary_messages = []
    
    # Load general context from text and markdown files
    general_context = load_context_files(CONTEXT_DIR)
    if general_context:
        summary_messages.append({"role": "user", "parts": [f"DODATKOWY KONTEKST KAMPANII:\n{general_context}"]})

    summary_messages.append({"role": "user", "parts": [f"TRANSKRYPT OBECNEJ SESJI:\n{transcript_content}"]})

    print("Generating detailed session summary...")
    summary_response = summary_model.generate_content(
        summary_messages,
        generation_config=genai.GenerationConfig(temperature=0.7),
    )
    session_summary = summary_response.text
    print("Session summary generated.")

    # --- Step 2: Extract Structured Details ---
    print("Waiting for API rate limit...")
    time.sleep(10)

    with open(DETAILS_PROMPT_FILE, "r", encoding='utf-8') as f:
        details_prompt = f.read()

    client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=details_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    print("Extracting structured details...")
    details_messages = [{
        "role": "user",
        "content": (
            f"PODSUMOWANIE SESJI (użyj do generowania tytułu, wydarzeń, NPC, lokacji, przedmiotów i propozycji na następną sesję):\n{session_summary}\n\n"
            f"PEŁNA TRANSKRYPCJA (użyj TYLKO do znalezienia pamiętnych cytatów):\n{transcript_content}"
        )
    }]

    session_data = client.chat.completions.create(
        messages=details_messages,
        response_model=SessionData,
        max_retries=3,
    )
    print("Session details extracted.")
    return session_summary, session_data

def save_summary_file(session_summary: str, session_data: SessionData, session_number: int, session_date: datetime.date):
    """Saves the generated notes to a formatted Markdown file."""
    with open(TEMPLATE_FILE, "r", encoding='utf-8') as f:
        template = f.read()

    output = template.format(
        number=session_number,
        title=session_data.title,
        date=session_date.strftime("%d.%m.%Y"),
        summary=session_summary,
        events="\n".join(f"* {event}" for event in session_data.events),
        npcs="\n".join(f"* {npc}" for npc in session_data.npcs),
        locations="\n".join(f"* {loc}" for loc in session_data.locations),
        items="\n".join(f"* {item}" for item in session_data.items),
        quotes="\n".join(f"* {quote}" for quote in session_data.quotes),
        hooks="\n".join(f"* {hook}" for hook in session_data.hooks),
        images="\n".join(f"* `{image}`" for image in session_data.images),
        videos="\n".join(f"* `{video}`" for video in session_data.videos),
    )

    sane_title = re.sub(r'[\\/*?:"<>|]', "", session_data.title)
    output_file = OUTPUT_DIR / f"Sesja {session_number} - {sane_title}.md"
    with open(output_file, "w", encoding='utf-8') as f:
        f.write(output)
    print(f"Session notes saved to {output_file}")

# --- Workflow Functions ---

def run_transcription_workflow():
    """Runs the workflow up to and including combining transcriptions."""
    start_time = time.time()
    print("\n[Step 1/4] Processing Chat Log...")
    session_number, session_date = process_chat_log()
    if session_number is None:
        print("❌ Error processing chat log. Aborting workflow.")
        return

    if session_date is None:
        today = datetime.date.today()
        session_date = today - datetime.timedelta(days=today.weekday())
        print(f"⚠️ Could not determine date. Defaulting to last Monday: {session_date.strftime('%Y-%m-%d')}")

    print(f"✅ Found Session Number: {session_number}")
    print(f"✅ Found Session Date: {session_date.strftime('%Y-%m-%d')}")

    print("\n[Step 2/4] Preparing Audio Files...")
    unzip_audio()
    print("✅ Audio files are ready.")

    print("\n[Step 3/4] Transcribing Audio...")
    transcribe_audio()
    print("✅ Transcription complete.")
    
    print("\n[Step 4/4] Combining Transcriptions...")
    transcript_file = combine_transcriptions(session_number)
    if not transcript_file:
         print("❌ Error combining transcriptions. Aborting workflow.")
         return
    print("✅ Transcriptions combined.")
    
    end_time = time.time()
    print(f"\n✨ Transcription workflow completed in {time.strftime('%H:%M:%S', time.gmtime(end_time - start_time))}. ✨")
    return transcript_file, session_number, session_date


def run_full_workflow():
    """Runs the entire workflow, including AI generation."""
    start_time = time.time()
    
    # Run the initial transcription part of the workflow
    transcription_result = run_transcription_workflow()
    if not transcription_result:
        return # Abort if the first part failed
    
    transcript_file, session_number, session_date = transcription_result

    print("\n[Step 5/5] Generating Session Notes with AI...")
    notes = generate_session_notes(transcript_file)
    if notes:
        summary, details = notes
        save_summary_file(summary, details, session_number, session_date)
        print("✅ AI-powered session notes have been generated and saved.")
    else:
        print("⚠️ AI note generation was skipped or failed.")

    end_time = time.time()
    print(f"\n✨ Full workflow completed in {time.strftime('%H:%M:%S', time.gmtime(end_time - start_time))}. ✨")

# --- Main Orchestration ---

def handle_temp_directory():
    """Checks for an existing temp directory and asks the user how to proceed."""
    if TEMP_DIR.exists() and any(TEMP_DIR.iterdir()):
        print("-" * 50)
        print(f"⚠️  Warning: Temporary directory '{TEMP_DIR}' already contains files.")
        print("Continuing may use old files or cause unexpected behavior.")
        
        while True:
            choice = input("Do you want to delete the existing temporary directory? [y/n]: ").lower().strip()
            if choice in ['y', 'yes']:
                try:
                    shutil.rmtree(TEMP_DIR)
                    print(f"🗑️  Temporary directory '{TEMP_DIR}' has been removed.")
                except Exception as e:
                    print(f"❌ Error removing temporary directory: {e}")
                    print("Please remove it manually and restart the script.")
                    sys.exit(1)
                break
            elif choice in ['n', 'no']:
                print("👍 Continuing with existing temporary files.")
                break
            else:
                print("Invalid choice. Please enter 'y' or 'n'.")
        print("-" * 50)

def display_menu():
    """Displays the main menu and handles user input."""
    print("\n" + "="*50)
    print("🚀 D&D Session Processing Workflow 🚀")
    print("="*50)
    print("Please choose an option:")
    print("  [1] Start Full Workflow (Transcribe -> Generate AI Notes)")
    print("  [2] Run Workflow until Transcribing (Generate transcript file only)")
    print("  [3] Exit")
    print("="*50)
    
    while True:
        choice = input("Enter your choice [1-4]: ").strip()
        if choice in ['1', '2', '3']:
            return choice
        else:
            print("❌ Invalid choice. Please enter a number from 1 to 3.")

def main():
    """Main function to orchestrate the entire workflow via a menu."""
    handle_temp_directory()
    
    # Always set up directories after handling the temp dir
    setup_directories()

    while True:
        choice = display_menu()

        if choice == '1':
            print("\nStarting Full Workflow...")
            run_full_workflow()
        
        elif choice == '2':
            print("\nStarting Transcription-Only Workflow...")
            run_transcription_workflow()

        elif choice == '3':
            print("\n👋 Exiting. Goodbye!")
            break
        
        print("\nReturning to main menu...")


if __name__ == "__main__":
    main()
