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
from pydantic import BaseModel, Field, field_validator
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
DELETE_TEMP_FILES = os.getenv("DELETE_TEMP_FILES", "False").lower() == "true"

# --- Setup Directories ---
# These are subdirectories for organized output
CHAT_LOG_OUTPUT_DIR = OUTPUT_DIR / "_chat_log"
TRANSCRIPTIONS_OUTPUT_DIR = OUTPUT_DIR / "_transcripts"
AUDIO_OUTPUT_DIR = TEMP_DIR / "audio"
TEMP_TRANSCRIPTIONS = TEMP_DIR / "transcriptions"

# Create all necessary directories if they don't exist
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
    """Loads all text files from the context directory into a single string."""
    context_data = ""
    if context_dir.exists():
        for file_path in context_dir.glob("*.txt"):
            try:
                with open(file_path, "r", encoding='utf-8') as f:
                    context_data += f.read() + "\n\n"
            except Exception as e:
                print(f"Error reading context file {file_path}: {e}")
    return context_data

# --- Main Processing Steps ---

def process_chat_log() -> int | None:
    """
    Finds the newest session chat log, extracts the session number from its filename,
    prettifies it, and saves it to the chat log output directory.
    """
    newest_chat_log = get_newest_file(CHAT_LOG_SOURCE_DIR, "session*.json")
    if not newest_chat_log:
        print("No session chat log found (e.g., 'session53.json').")
        return None

    # Extract session number from the filename (e.g., "session53.json" -> 53)
    match = re.search(r'session(\d+)', newest_chat_log.name)
    if not match:
        print(f"Could not extract session number from filename: {newest_chat_log.name}")
        return None
    session_number = int(match.group(1))

    output_filepath = CHAT_LOG_OUTPUT_DIR / f"session{session_number}.json"
    if output_filepath.exists():
        print(f"Chat log for session {session_number} already exists. Skipping processing.")
        return session_number

    prettified_json_string = prettify_json(newest_chat_log)
    if not prettified_json_string:
        return None

    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write(prettified_json_string)
    print(f"Prettified chat log saved to: {output_filepath}")

    return session_number

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
            discord_user = json_file.stem.split("-", 1)[1].split("_")[0]
            speaker = discord_character_mapping.get(discord_user, discord_user)
        except IndexError:
            print(f"Warning: Could not extract speaker from {json_file.name}. Using filename stem.")
            speaker = json_file.stem

        with open(json_file, "r", encoding='utf-8') as f:
            segments = json.load(f)
            for segment in segments:
                # Filter out low-confidence or junk segments
                if segment.get("no_speech_prob", 0.0) > 0.4 or not segment['text'].strip():
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
    images: list[str] = Field(
        description="""Lista 3-5 promptów do użycia w generatorach obrazów AI, **napisanych w języku angielskim**.
                       Każdy prompt powinien zaczynać się od słowa 'Draw'.
                       Unikaj nazw własnych postaci, zamiast tego opisz ich wygląd i akcję.
                       Stosuj różnorodne style artystyczne (np. 'oil painting', 'fantasy art', 'cinematic')."""
    )
    date: datetime.date | None = Field(default=None, description="Data sesji w formacie YYYY-MM-DD. Jeśli nie jest znana, pozostaw null.")

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, value):
        if not value:
            # Default to the most recent Monday if no date is found
            today = datetime.date.today()
            return today - datetime.timedelta(days=today.weekday())
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                try:
                    return datetime.datetime.strptime(value, fmt).date()
                except ValueError:
                    pass
            raise ValueError("Incorrect date format. Expected YYYY-MM-DD or DD.MM.YYYY.")
        return value

def get_previous_summary_file(session_number: int) -> Path | None:
    """Retrieves the filepath of the previous session's summary markdown file."""
    previous_session_number = session_number - 1
    if previous_session_number > 0:
        # Glob for files matching the pattern "Sesja X - *.md"
        potential_files = list(OUTPUT_DIR.glob(f"Sesja {previous_session_number} - *.md"))
        if potential_files:
            # Return the newest one if multiple exist for some reason
            return max(potential_files, key=os.path.getmtime)
    return None

def generate_session_notes(transcript_file: Path, session_number: int) -> tuple[str, SessionData] | None:
    """Generates a detailed summary and structured data using the Gemini API."""
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set in .env file. Skipping note generation.")
        return None
        
    genai.configure(api_key=GEMINI_API_KEY)
    context_data = load_context_files(CONTEXT_DIR)

    # --- Step 1: Generate Detailed Summary ---
    with open(SUMMARY_PROMPT_FILE, "r", encoding='utf-8') as f:
        summary_prompt = f.read()

    summary_model = genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=summary_prompt,
    )
    
    summary_messages = []
    if context_data:
        summary_messages.append({"role": "user", "parts": [f"DODATKOWY KONTEKST:\n{context_data}"]})

    previous_summary_file = get_previous_summary_file(session_number)
    if previous_summary_file:
        print(f"Using previous summary for context: {previous_summary_file.name}")
        with open(previous_summary_file, "r", encoding='utf-8') as f:
            prev_summary = f.read()
            summary_messages.append({"role": "user", "parts": [f"PODSUMOWANIE POPRZEDNIEJ SESJI:\n{prev_summary}"]})

    with open(transcript_file, "r", encoding='utf-8') as f:
        transcript_content = f.read()
        summary_messages.append({"role": "user", "parts": [f"TRANSKRYPT OBECNEJ SESJI:\n{transcript_content}"]})

    print("Generating detailed session summary...")
    summary_response = summary_model.generate_content(
        summary_messages,
        generation_config=genai.GenerationConfig(temperature=0.7),
    )
    session_summary = summary_response.text
    print("Session summary generated.")

    # --- Step 2: Extract Structured Details from the Summary ---
    print("Waiting for API rate limit...")
    time.sleep(10) # Simple delay to avoid hitting rate limits

    with open(DETAILS_PROMPT_FILE, "r", encoding='utf-8') as f:
        details_prompt = f.read()

    client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=details_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    print("Extracting structured details from summary...")
    details_messages = [{"role": "user", "content": session_summary}]

    session_data = client.chat.completions.create(
        messages=details_messages,
        response_model=SessionData,
        max_retries=3,
    )
    print("Session details extracted.")
    return session_summary, session_data

def save_summary_file(session_summary: str, session_data: SessionData, session_number: int):
    """Saves the generated notes to a formatted Markdown file."""
    with open(TEMPLATE_FILE, "r", encoding='utf-8') as f:
        template = f.read()

    output = template.format(
        number=session_number,
        title=session_data.title,
        date=session_data.date.strftime("%d.%m.%Y"),
        summary=session_summary,
        events="\n".join(f"* {event}" for event in session_data.events),
        npcs="\n".join(f"* {npc}" for npc in session_data.npcs),
        locations="\n".join(f"* {loc}" for loc in session_data.locations),
        items="\n".join(f"* {item}" for item in session_data.items),
        images="\n".join(f"* `{image}`" for image in session_data.images),
    )

    output_file = OUTPUT_DIR / f"Sesja {session_number} - {session_data.title}.md"
    with open(output_file, "w", encoding='utf-8') as f:
        f.write(output)
    print(f"Session notes saved to {output_file}")


# --- Main Orchestration ---

def main():
    """Main function to orchestrate the entire workflow."""
    start_time = time.time()
    print("🚀 Starting D&D Session Processing Workflow...")

    print("\n[Step 1/5] Processing Chat Log...")
    session_number = process_chat_log()
    if session_number is None:
        print("❌ Error processing chat log. Exiting.")
        sys.exit(1)
    print(f"✅ Found Session Number: {session_number}")

    print("\n[Step 2/5] Preparing Audio Files...")
    unzip_audio()
    print("✅ Audio files are ready.")

    print("\n[Step 3/5] Transcribing Audio (this may take a while)...")
    transcribe_audio()
    print("✅ Transcription complete.")
    
    print("\n[Step 4/5] Combining Transcriptions...")
    transcript_file = combine_transcriptions(session_number)
    if not transcript_file:
         print("❌ Error combining transcriptions. Exiting.")
         sys.exit(1)
    print("✅ Transcriptions combined.")

    print("\n[Step 5/5] Generating Session Notes with AI...")
    notes = generate_session_notes(transcript_file, session_number)
    if notes:
        summary, details = notes
        save_summary_file(summary, details, session_number)
        print("✅ AI-powered session notes have been generated and saved.")
    else:
        print("⚠️ AI note generation was skipped.")


    if DELETE_TEMP_FILES:
        try:
            shutil.rmtree(TEMP_DIR)
            print(f"\n🗑️ Temporary directory '{TEMP_DIR}' has been removed.")
        except Exception as e:
            print(f"Error removing temporary directory: {e}")

    end_time = time.time()
    print(f"\n✨ Workflow completed in {time.strftime('%H:%M:%S', time.gmtime(end_time - start_time))}. ✨")


if __name__ == "__main__":
    main()