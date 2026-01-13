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
from pydantic import BaseModel, Field, ValidationError
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
QUOTES_PROMPT_FILE = Path(os.getenv("QUOTES_PROMPT_FILE"))
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


def transcribe_audio() -> bool:
    """
    Transcribes all FLAC audio files in the audio directory using Whisper.
    Returns True if successful, False if an error occurred.
    """
    model_name = "large"
    device = "cuda" # 'cuda' for NVIDIA/AMD GPUs via ROCm

    # Check if all audio files are already transcribed
    audio_files = sorted(AUDIO_OUTPUT_DIR.glob("*.flac"), key=os.path.getsize)
    files_to_transcribe = [
        f for f in audio_files
        if not (TEMP_TRANSCRIPTIONS / f"{f.stem}.json").exists()
    ]

    if not files_to_transcribe:
        print("All audio files already transcribed. Skipping.")
        return True

    # Inject custom progress bar into Whisper
    transcribe_module = sys.modules['whisper.transcribe']
    transcribe_module.tqdm.tqdm = _CustomProgressBar

    try:
        model = whisper.load_model(model_name, device=device, download_root="./models/")
    except Exception as e:
        print(f"❌ Error loading Whisper model: {e}")
        print("Ensure you have a compatible ROCm/CUDA version installed.")
        return False

    with open(WHISPER_PROMPT_FILE, "r", encoding='utf-8') as f:
        initial_prompt = f.read().strip()

    for audio_file in tqdm(files_to_transcribe, desc="Transcribing Audio"):
        json_output_path = TEMP_TRANSCRIPTIONS / f"{audio_file.stem}.json"
        print(f"Transcribing {audio_file.name}...")
        try:
            result = model.transcribe(
                str(audio_file),
                language="pl",
                initial_prompt=initial_prompt,
                fp16=False 
            )
            with open(json_output_path, "w", encoding='utf-8') as f:
                json.dump(result["segments"], f, indent=2, ensure_ascii=False)
            print(f"\nTranscription of '{audio_file.name}' saved.")
            
        except Exception as e:
            print(f"\n❌ CRITICAL ERROR transcribing '{audio_file.name}': {e}")
            return False

    return True


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

class SectionVisuals(BaseModel):
    """Visual prompts for a specific section of the summary."""
    section_title: str = Field(description="Dokładny nagłówek ### z podsumowania, do którego odnoszą się te wizualizacje.")
    images: list[str] = Field(description="Lista 2 szczegółowych promptów obrazów dla tej sekcji. Minimum 50 słów każdy, używając opisów wizualnych postaci.")
    videos: list[str] = Field(description="Lista 2 szczegółowych promptów wideo dla tej sekcji. Minimum 50 słów każdy, z ruchem kamery i dynamiką.")

class SessionData(BaseModel):
    """Pydantic model for structuring data extracted by Gemini."""
    title: str = Field(description="Tytuł sesji. Powinien być krótki, ale opisowy i chwytliwy.")
    events: list[str] = Field(description="Krótka, punktowa lista najważniejszych wydarzeń lub decyzji, które miały miejsce.")
    npcs: list[str] = Field(description="Lista najważniejszych postaci niezależnych (NPC), które pojawiły się lub odegrały kluczową rolę.")
    locations: list[str] = Field(description="Lista najważniejszych odwiedzonych lokacji.")
    items: list[str] = Field(description="Lista najważniejszych zdobytych lub użytych przedmiotów.")
    main_images: list[str] = Field(
        description="""Lista 3 szczegółowych promptów obrazów reprezentujących całą sesję (wyświetlane pod tytułem).
                       Każdy prompt minimum 50 słów, używając pełnych opisów wizualnych postaci.
                       Napisane w języku angielskim, zaczynające się od 'Draw', 'Generate' itp."""
    )
    main_videos: list[str] = Field(
        description="""Lista 3 szczegółowych promptów wideo reprezentujących całą sesję (wyświetlane pod tytułem).
                       Każdy prompt minimum 50 słów, z ruchem kamery i dynamiką sceny.
                       Napisane w języku angielskim."""
    )
    sections: list[SectionVisuals] = Field(
        description="""Lista sekcji wizualnych, po jednej dla każdego nagłówka ### z podsumowania.
                       Każda sekcja zawiera section_title (dokładny nagłówek ###), 2 prompty obrazów i 2 prompty wideo."""
    )

class QuotesData(BaseModel):
    """Pydantic model for memorable quotes extracted from transcription."""
    quotes: list[str] = Field(
        description="Lista 5-7 najbardziej pamiętnych, zabawnych lub ważnych cytatów z sesji, wraz z informacją, kto je wypowiedział. Np. 'Arevon: \"Coś tu jest nie tak.\"'."
    )

def generate_session_notes(transcript_file: Path) -> tuple[str, SessionData, QuotesData] | None:
    """Generates a detailed summary, structured data, and quotes using the Gemini API."""
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

    # --- Step 2: Extract Structured Details (from summary only) ---
    print("Waiting for API rate limit...")
    time.sleep(10)

    with open(DETAILS_PROMPT_FILE, "r", encoding='utf-8') as f:
        details_prompt = f.read()

    details_client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=details_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    print("Extracting structured details...")
    details_messages = [{
        "role": "user",
        "content": f"PODSUMOWANIE SESJI:\n{session_summary}"
    }]

    session_data = details_client.chat.completions.create(
        messages=details_messages,
        response_model=SessionData,
        max_retries=3,
    )
    print("Session details extracted.")

    # --- Step 3: Extract Quotes (from transcription) ---
    print("Waiting for API rate limit...")
    time.sleep(10)

    with open(QUOTES_PROMPT_FILE, "r", encoding='utf-8') as f:
        quotes_prompt = f.read()

    quotes_client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=quotes_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    print("Extracting memorable quotes...")
    quotes_messages = [{
        "role": "user",
        "content": f"PEŁNA TRANSKRYPCJA:\n{transcript_content}"
    }]

    quotes_data = quotes_client.chat.completions.create(
        messages=quotes_messages,
        response_model=QuotesData,
        max_retries=3,
    )
    print("Quotes extracted.")

    return session_summary, session_data, quotes_data

def save_summary_file(session_summary: str, session_data: SessionData, quotes_data: QuotesData, session_number: int, session_date: datetime.date):
    """Saves the generated notes to a formatted Markdown file."""
    with open(TEMPLATE_FILE, "r", encoding='utf-8') as f:
        template = f.read()

    # Process summary to embed section-specific visuals after each section
    processed_summary = session_summary
    for section in session_data.sections:
        # Find the section header in the summary
        print(section.section_title.lstrip('# '))
        section_header = f"### {section.section_title.lstrip('# ')}"
        if section_header in processed_summary:
            # Build the visual prompts block for this section
            section_visuals = "\n\n**Propozycje Obrazów dla tej sekcji:**\n"
            section_visuals += "\n".join(f"* `{img}`" for img in section.images)
            section_visuals += "\n\n**Propozycje Wideo dla tej sekcji:**\n"
            section_visuals += "\n".join(f"* `{vid}`" for vid in section.videos)
            
            # Find the next section header or end of summary
            header_pos = processed_summary.find(section_header)
            next_header_pos = processed_summary.find("\n### ", header_pos + len(section_header))
            
            if next_header_pos == -1:
                # This is the last section, append at the end
                processed_summary = processed_summary + section_visuals
            else:
                # Insert before the next section header
                processed_summary = (
                    processed_summary[:next_header_pos] +
                    section_visuals + "\n" +
                    processed_summary[next_header_pos:]
                )

    output = template.format(
        number=session_number,
        title=session_data.title,
        date=session_date.strftime("%d.%m.%Y"),
        summary=processed_summary,
        events="\n".join(f"* {event}" for event in session_data.events),
        npcs="\n".join(f"* {npc}" for npc in session_data.npcs),
        locations="\n".join(f"* {loc}" for loc in session_data.locations),
        items="\n".join(f"* {item}" for item in session_data.items),
        quotes="\n".join(f"* {quote}" for quote in quotes_data.quotes),
        main_images="\n".join(f"* `{image}`" for image in session_data.main_images),
        main_videos="\n".join(f"* `{video}`" for video in session_data.main_videos),
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
    if not transcribe_audio():
        print("❌ Transcription failed. Aborting workflow to prevent incomplete data.")
        return None
    print("✅ Transcription complete.")

    print("\n[Step 4/4] Combining Transcriptions...")
    transcript_file = combine_transcriptions(session_number)
    if not transcript_file:
         print("❌ Error combining transcriptions. Aborting workflow.")
         return None
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
        summary, details, quotes = notes
        save_summary_file(summary, details, quotes, session_number, session_date)
        print("✅ AI-powered session notes have been generated and saved.")
    else:
        print("⚠️ AI note generation was skipped or failed.")

    end_time = time.time()
    print(f"\n✨ Full workflow completed in {time.strftime('%H:%M:%S', time.gmtime(end_time - start_time))}. ✨")


def run_manual_workflow():
    """Handles the workflow for manually entering session notes."""
    print("\n--- Manual Entry Workflow ---")
    
    # 1. Get session number and date from the latest chat log
    print("\n[Step 1/4] Reading session info from the latest chat log...")
    session_number, session_date = process_chat_log()
    if session_number is None:
        print("❌ Error processing chat log. Cannot proceed without a session number. Aborting.")
        return

    # Handle missing date, just like in the other workflows
    if session_date is None:
        today = datetime.date.today()
        session_date = today - datetime.timedelta(days=today.weekday())
        print(f"⚠️ Could not determine date from chat log. Defaulting to last Monday: {session_date.strftime('%Y-%m-%d')}")

    print(f"✅ Found Session Number: {session_number}")
    print(f"✅ Found Session Date: {session_date.strftime('%Y-%m-%d')}")

    # 2. Get the summary text from the user
    print("\n[Step 2/4] Enter the session summary.")
    print("Paste your summary below. Press Ctrl+D (Unix) or Ctrl+Z then Enter (Windows) to finish.")
    session_summary = sys.stdin.read().strip()
    if not session_summary:
        print("❌ Summary is empty. Aborting.")
        return
    print("✅ Summary received.")

    # 3. Get the details JSON from the user and validate it
    print("\n[Step 3/4] Enter the session details as JSON.")
    print("Paste the JSON data below. Press Ctrl+D (Unix) or Ctrl+Z then Enter (Windows) to finish.")
    
    session_data = None
    while session_data is None:
        try:
            # Re-enable stdin reading if it was closed
            if sys.stdin.isatty() is False:
                sys.stdin = open('/dev/tty')
                
            json_input = sys.stdin.read().strip()
            if not json_input:
                print("❌ JSON input is empty. Aborting.")
                return
            
            # Use Pydantic to parse and validate the JSON input
            session_data = SessionData.model_validate_json(json_input)
            print("✅ Session details JSON is valid.")
            
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"❌ Data is invalid: {e}")
            choice = input("Would you like to try again? [y/n]: ").lower()
            if choice not in ['y', 'yes']:
                print("Aborting.")
                return
            print("Please paste the JSON data again:")

    # 4. Get the quotes JSON from the user and validate it
    print("\n[Step 4/4] Enter the quotes as JSON.")
    print("Paste the JSON data below. Press Ctrl+D (Unix) or Ctrl+Z then Enter (Windows) to finish.")
    
    quotes_data = None
    while quotes_data is None:
        try:
            # Re-enable stdin reading if it was closed
            if sys.stdin.isatty() is False:
                sys.stdin = open('/dev/tty')
                
            json_input = sys.stdin.read().strip()
            if not json_input:
                print("❌ JSON input is empty. Aborting.")
                return
            
            # Use Pydantic to parse and validate the JSON input
            quotes_data = QuotesData.model_validate_json(json_input)
            print("✅ Quotes JSON is valid.")
            
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"❌ Data is invalid: {e}")
            choice = input("Would you like to try again? [y/n]: ").lower()
            if choice not in ['y', 'yes']:
                print("Aborting.")
                return
            print("Please paste the JSON data again:")

    # 5. Save the final file using the existing function
    save_summary_file(session_summary, session_data, quotes_data, session_number, session_date)
    print("\n✨ Manual entry workflow completed successfully. ✨")

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
    print("  [3] Manual Note Entry (from existing summary/details)")
    print("  [4] Exit")
    print("="*50)
    
    while True:
        choice = input("Enter your choice [1-4]: ").strip()
        if choice in ['1', '2', '3', '4']:
            return choice
        else:
            print("❌ Invalid choice. Please enter a number from 1 to 4.")

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
            print("\nStarting Manual Entry Workflow...")
            run_manual_workflow()

        elif choice == '4':
            print("\n👋 Exiting. Goodbye!")
            break

if __name__ == "__main__":
    main()
