import os
import sys
import glob
import zipfile
import json
import datetime
import time
import shutil
from pathlib import Path

import whisper
import instructor
import google.generativeai as genai
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables
load_dotenv()

# --- Configuration (from .env) ---
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR"))
TEMP_DIR = Path(os.getenv("TEMP_DIR"))
CHAT_LOG_SOURCE_DIR = Path(os.getenv("CHAT_LOG_SOURCE_DIR"))
AUDIO_SOURCE_DIR = Path(os.getenv("AUDIO_SOURCE_DIR"))
DISCORD_MAPPING_FILE = Path(os.getenv("DISCORD_MAPPING_FILE"))
WHISPER_PROMPT_FILE = Path(os.getenv("WHISPER_PROMPT_FILE"))
SUMMARY_PROMPT_FILE = Path(os.getenv("SUMMARY_PROMPT_FILE"))
DETAILS_PROMPT_FILE = Path(os.getenv("DETAILS_PROMPT_FILE"))
TEMPLATE_FILE = Path(os.getenv("TEMPLATE_FILE"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DELETE_TEMP_FILES = os.getenv("DELETE_TEMP_FILES", "False").lower() == "true"
CONTEXT_DIR = Path(os.getenv("CONTEXT_DIR"))
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME")

# --- Setup Directories ---
CHAT_LOG_OUTPUT_DIR = OUTPUT_DIR / "_chat_log"
TRANSCRIPTIONS_OUTPUT_DIR = OUTPUT_DIR / "_transcripts"
AUDIO_OUTPUT_DIR = TEMP_DIR / "audio"
TEMP_TRANSCRIPTIONS =  TEMP_DIR / "transcriptions"

for directory in [OUTPUT_DIR, TEMP_DIR, CHAT_LOG_OUTPUT_DIR, AUDIO_OUTPUT_DIR, TRANSCRIPTIONS_OUTPUT_DIR, TEMP_TRANSCRIPTIONS, CONTEXT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# --- Helper Functions ---

def get_newest_file(directory, pattern):
    """Finds the newest file matching the given pattern in a directory."""
    files = glob.glob(os.path.join(directory, pattern))
    return max(files, key=os.path.getmtime) if files else None

def prettify_json(filepath):
    """Reads, prettifies, and returns JSON data from a file."""
    try:
        with open(filepath, 'r') as f:
            json_data = json.load(f)
        return json.dumps(json_data, indent=2)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error processing JSON in {filepath}: {e}")
        return None

def extract_session_number(json_data):
    """Extracts the session number from the 'title' field in JSON data."""
    try:
        title = json_data.get("data", {}).get("title")
        return int(title.split()[-1]) if title else None
    except (AttributeError, ValueError, IndexError) as e:
        print(f"Error extracting session number: {e}")
        return None

def load_context_files(context_dir):
    """Loads all text files from the context directory."""
    context_data = ""
    if context_dir:
        for file_path in context_dir.glob("*.txt"):
            try:
                with open(file_path, "r") as f:
                    context_data += f.read() + "\n\n"
            except Exception as e:
                print(f"Error reading context file {file_path}: {e}")
    return context_data

# --- Chat Log Processing ---

def process_chat_log():
    """Processes the newest chat log, prettifies it, and saves it with the session number."""
    session_number = None

    newest_chat_log = get_newest_file(CHAT_LOG_SOURCE_DIR, "*.json")
    if not newest_chat_log:
        print("No chat log found.")
        return None

    with open(newest_chat_log, 'r') as f:
        original_json_data = json.load(f)

    session_number = extract_session_number(original_json_data)
    if not session_number:
        return None

    # Check if chat log for this session already exists
    if (CHAT_LOG_OUTPUT_DIR / f"session{session_number}.json").exists():
        print(f"Chat log for session {session_number} already exists. Skipping.")
        return session_number

    prettified_json_string = prettify_json(newest_chat_log)
    if not prettified_json_string:
        return None

    if session_number:
        output_filepath = CHAT_LOG_OUTPUT_DIR / f"session{session_number}.json"
        with open(output_filepath, 'w') as f:
            f.write(prettified_json_string)
        print(f"Prettified chat log saved to: {output_filepath}")

    return session_number

# --- Audio Processing ---

def unzip_audio():
    """Unzips the newest FLAC zip file to the audio output directory."""

    # Check if audio files already exist
    if any(AUDIO_OUTPUT_DIR.glob("*.flac")):
        print("Audio files already exist. Skipping unzip.")
        return

    newest_zip = get_newest_file(AUDIO_SOURCE_DIR, "craig-*.flac.zip")
    if not newest_zip:
        print("No matching audio zip file found.")
        return

    try:
        with zipfile.ZipFile(newest_zip, 'r') as zip_ref:
            zip_ref.extractall(AUDIO_OUTPUT_DIR)
        print(f"Extracted audio to: {AUDIO_OUTPUT_DIR}")

        # Delete non-FLAC files
        for filename in os.listdir(AUDIO_OUTPUT_DIR):
            file_path = AUDIO_OUTPUT_DIR / filename
            if file_path.is_file() and not filename.endswith(".flac"):
                os.remove(file_path)
                print(f"Deleted: {file_path}")

        os.remove(newest_zip)
        print(f"Deleted zip file: {newest_zip}")

    except zipfile.BadZipFile:
        print(f"Error: {newest_zip} is not a valid zip file.")

# --- Audio Transcription ---

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
    """Transcribes FLAC audio files using Whisper."""
    model_name = "large"
    device = "cuda"

    should_transcribe = False
    audio_files = sorted(AUDIO_OUTPUT_DIR.glob("*.flac"), key=os.path.getsize)
    for audio_file in audio_files:
        json_output_path = TEMP_TRANSCRIPTIONS / f"{audio_file.stem}.json"
        if json_output_path.exists():
            continue
        should_transcribe = True

    if not should_transcribe:
        print(f"All audio files already transcribed. Skipping.")
        return

    # Inject custom progress bar into Whisper
    transcribe_module = sys.modules['whisper.transcribe']
    transcribe_module.tqdm.tqdm = _CustomProgressBar

    try:
        model = whisper.load_model(model_name, device=device, download_root="./models/")
    except RuntimeError as e:
        print(f"Error loading Whisper model: {e}")
        print("Ensure you have a compatible CUDA version or use device='cpu'.")
        return

    with open(WHISPER_PROMPT_FILE, "r") as f:
        initial_prompt = f.read().strip()

    for audio_file in audio_files:
        json_output_path = TEMP_TRANSCRIPTIONS / f"{audio_file.stem}.json"
        if json_output_path.exists():
            print(f"Skipping '{audio_file.name}' (already transcribed).")
            continue

        print(f"Transcribing {audio_file.name}...")
        try:
            result = model.transcribe(
                str(audio_file),
                language="pl",
                initial_prompt=initial_prompt
            )
            with open(json_output_path, "w") as f:
                json.dump(result["segments"], f, indent=2)
            print(f"\nTranscription of '{audio_file.name}' saved to '{json_output_path}'.")
        except Exception as e:
            print(f"Error transcribing '{audio_file.name}': {e}")

# --- Combine Transcriptions ---

def combine_transcriptions(session_number):
    """Combines JSON transcriptions, adds speaker labels, and creates a TXT file."""

    combined_json_path = TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.json"
    combined_txt_path = TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.txt"

    # Check if combined files already exist
    if combined_json_path.exists() and combined_txt_path.exists():
        print(f"Combined transcriptions for session {session_number} already exist. Skipping.")
        return combined_txt_path

    try:
        with open(DISCORD_MAPPING_FILE, "r") as f:
            discord_character_mapping = json.load(f)
    except FileNotFoundError:
        print(f"Warning: Mapping file '{DISCORD_MAPPING_FILE}' not found. Using raw Discord usernames.")
        discord_character_mapping = {}

    all_segments = []
    for json_file in TEMP_TRANSCRIPTIONS.glob("*.json"):
        try:
            discord_user = json_file.stem.split("-")[1].lstrip("_").split("_")[0]
            speaker = discord_character_mapping.get(discord_user, discord_user)
        except IndexError:
            print(f"Warning: Could not extract speaker from {json_file.name}. Skipping.")
            continue

        with open(json_file, "r") as f:
            segments = json.load(f)
            last_segment_text = None
            for segment in segments:
                if segment["no_speech_prob"] > 0.3 or segment["text"].strip() in ["Dziękuję.", " ..."]:
                    continue
                current_text = segment["text"].strip()
                if last_segment_text == current_text:
                    continue
                segment["speaker"] = speaker
                last_segment_text = current_text
                all_segments.append(segment)

    all_segments.sort(key=lambda x: x["start"])

    with open(combined_json_path, "w") as f:
        json.dump(all_segments, f, indent=2)

    with open(combined_txt_path, "w") as f:
        current_speaker = None
        for segment in all_segments:
            if segment["speaker"] != current_speaker:
                f.write(f"\n\n[{segment['speaker']}]\n")
                current_speaker = segment["speaker"]
            f.write(segment["text"].strip() + " ")

    print(f"Combined transcription saved to {combined_json_path} and {combined_txt_path}")
    return combined_txt_path

# --- Generate Session Notes ---

class SessionData(BaseModel):
    """Pydantic model for session data extracted by Gemini."""
    number: int | None = Field(description="Numer sesji.")
    date: datetime.date | None = Field(description="Data sesji. Spróbuj znaleźć w kontekście lub użyj daty z ostatniego poniedziałku.")
    events: list[str] = Field(description="Krótka lista najważniejszych wydarzeń lub decyzji.")
    title: str = Field(description="Tytuł sesji. Powinien być krótki, ale opisowy.")
    npcs: list[str] = Field(description="Krótka lista najważniejszych NPCów.")
    locations: list[str] = Field(description="Krótka lista najważniejszych lokacji.")
    items: list[str] = Field(description="Krótka lista najważniejszych przedmiotów.")
    images: list[str] = Field(description="""Lista promptów do użycia w generatorach obrazów AI w **języku angielskim**.
                              Staraj się nie używać nazw własnych, zastąp imiona bohaterów opisem ich wyglądu.
                              Używaj różnych stylów artystycznych. Zacznij każdy od słowa 'Draw'.""")

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, value):
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                try:
                    return datetime.datetime.strptime(value, fmt).date()
                except ValueError:
                    pass
            raise ValueError("Incorrect date format. Expected YYYY-MM-DD or DD.MM.YYYY.")

        return value or (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday()))

def generate_session_notes(transcript_file, session_number):
    """Generates session notes using the Gemini API."""
    genai.configure(api_key=GEMINI_API_KEY)
    context_data = load_context_files(CONTEXT_DIR)

    # --- Generate Detailed Summary ---
    with open(SUMMARY_PROMPT_FILE, "r") as f:
        summary_prompt = f.read()

    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=summary_prompt,
    )

    summary_messages = [
        {"role": "user", "parts": ["Bardzo proszę, napisz szczegółowe i długie podsumowanie."]},
    ]

    if context_data:
        summary_messages.append({"role": "user", "parts": ["Dodatkowy kontekst:\n", context_data]})

    # Add previous summary for context if available
    previous_summary_file = get_previous_summary_file(session_number)
    if previous_summary_file:
        print("Using previous summary for additional context.")
        with open(previous_summary_file, "r") as f:
            summary_messages.append({"role": "user", "parts": ["Podsumowanie z poprzedniej sesji dla dodatkowego kontekstu:\n", f.read()]})

    with open(transcript_file, "r") as f:
        summary_messages.append({"role": "user", "parts": ["Transkrypt:\n", f.read()]})

    summary_response = model.generate_content(
        summary_messages,
        generation_config=genai.GenerationConfig(),
        stream=False
    )
    session_summary = summary_response.text
    print("Session summary generated.")

    print(f"Session Summary: {session_summary=}")

    # --- Generate Details (Title, Events, etc.) ---
    print("Waiting for 10 seconds for next request.")
    time.sleep(10)

    with open(DETAILS_PROMPT_FILE, "r") as f:
        details_prompt = f.read()

    client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=details_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    details_messages = [
            {"role": "user", "content": "Bardzo proszę wyciągnij szczegóły z poniższego podsumowania."},
            {"role": "user", "content": session_summary},
        ]
    if context_data:
        details_messages.append({"role": "user", "parts": ["Dodatkowy kontekst:\n", context_data]})
    session_data = client.chat.completions.create(
        messages=details_messages,
        response_model=SessionData,
        max_retries=3,
    )
    print("Session details generated.")
    return session_summary, session_data

def get_previous_summary_file(session_number):
    """Retrieves the filepath of the previous session's summary, if it exists."""
    previous_session_number = session_number - 1
    if previous_session_number > 0:
        potential_previous_summary = OUTPUT_DIR / f"Sesja {previous_session_number} - *.md"
        previous_summary_files = sorted(
            potential_previous_summary.parent.glob(potential_previous_summary.name),
            key=os.path.getmtime,
            reverse=True
        )
        if previous_summary_files:
            return previous_summary_files[0]
    return None

def save_summary_file(session_summary, session_data, session_number):
    """Saves the generated summary to a Markdown file."""
    with open(TEMPLATE_FILE, "r") as f:
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
        images="\n".join(f"* {image}" for image in session_data.images),
    )

    output_file = OUTPUT_DIR / f"Sesja {session_number} - {session_data.title}.md"
    with open(output_file, "w") as f:
        f.write(output)
    print(f"Session notes saved to {output_file}")

# --- Main Function ---

def main():
    """Main function to orchestrate the workflow."""
    print("Starting workflow...")

    print("1. Processing chat log...")
    session_number = process_chat_log()
    if session_number is None:
        print("Error processing chat log. Exiting.")
        sys.exit(1)
    print("Session number:", session_number)

    print("2. Unzipping audio files...")
    unzip_audio()

    print("3. Transcribing audio files...")
    transcribe_audio()

    print("4. Combining transcriptions...")
    transcript_file = combine_transcriptions(session_number)

    print("5. Generating session summary...")
    summary, details = generate_session_notes(transcript_file, session_number)
    save_summary_file(summary, details, session_number)

    # Delete temporary files if configured
    if DELETE_TEMP_FILES:
        try:
            shutil.rmtree(TEMP_DIR)
            print(f"Temporary directory '{TEMP_DIR}' removed.")
        except Exception as e:
            print(f"Error removing temporary directory: {e}")

    print("Workflow completed successfully!")

if __name__ == "__main__":
    main()
