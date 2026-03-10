import os
import sys
import glob
import zipfile
import json
import datetime
import time
import shutil
import re
import logging
from pathlib import Path
from string import Template

import whisper
import instructor
import google.generativeai as genai
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables from a .env file
load_dotenv()

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("session_processor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# --- Configuration (loaded from .env file) ---

def _require_env(key: str) -> str:
    """Reads an env var and raises a clear error if it's missing or empty."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is missing or empty in your .env file."
        )
    return val

def _require_path(key: str) -> Path:
    """Reads an env var as a Path, raising a clear error if missing."""
    return Path(_require_env(key))

# Main directories
OUTPUT_DIR            = _require_path("OUTPUT_DIR")
TEMP_DIR              = _require_path("TEMP_DIR")
DOWNLOADS_DIR         = _require_path("DOWNLOADS_DIR")

# Source directories are the same as downloads
CHAT_LOG_SOURCE_DIR   = DOWNLOADS_DIR
AUDIO_SOURCE_DIR      = DOWNLOADS_DIR

# Configuration files and context
DISCORD_MAPPING_FILE  = _require_path("DISCORD_MAPPING_FILE")
WHISPER_PROMPT_FILE   = _require_path("WHISPER_PROMPT_FILE")
SUMMARY_PROMPT_FILE   = _require_path("SUMMARY_PROMPT_FILE")
DETAILS_PROMPT_FILE   = _require_path("DETAILS_PROMPT_FILE")
QUOTES_PROMPT_FILE    = _require_path("QUOTES_PROMPT_FILE")
TEMPLATE_FILE         = _require_path("TEMPLATE_FILE")
CONTEXT_DIR           = _require_path("CONTEXT_DIR")

# API and Model Settings
GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY")
GEMINI_PRO_MODEL      = os.getenv("GEMINI_PRO_MODEL")
GEMINI_FLASH_MODEL    = os.getenv("GEMINI_FLASH_MODEL")

# Rate-limit pause between consecutive Gemini API calls (seconds)
GEMINI_API_SLEEP_SECS = 3

# --- Setup Directories ---
# Recap docs go here
SESSIONS_RECAP_DIR = OUTPUT_DIR / "01-Sessions"
# All generated session assets (logs, transcripts) go here
ASSETS_BASE_DIR    = OUTPUT_DIR / "assets" / "sessions"

AUDIO_OUTPUT_DIR         = TEMP_DIR / "audio"
TEMP_TRANSCRIPTIONS      = TEMP_DIR / "transcriptions"
PROCESSED_DIR            = DOWNLOADS_DIR / "_processed"

# --- Hallucination blocklist ---
HALLUCINATION_BLOCKLIST: frozenset[str] = frozenset({
    # Whisper/YouTube subtitle artifacts
    "napisy by", "napisy stworzone przez", "napisy pobrane z",
    "jacek makarewicz", "subtitles by", "subtitle by",
    "captioned by", "translated by", "amara.org",
    "org community", "ted.com", "ted talks",
    # YouTube outros
    "dzięki za oglądanie", "dziękuję za oglądanie",
    "thanks for watching", "proszę o subskrypcję",
    "nie zapomnij zasubskrybować", "kliknij dzwoneczek",
    "like, share and subscribe",
    # Copyright / legal
    "wszelkie prawa zastrzeżone", "all rights reserved", "copyright",
    # Unicode glitches
    "ï¿½", "â",
    # Audio descriptions
    "[muzyka]", "(muzyka)", "[cisza]", "(cisza)", "[music]", "(music)",
})


def setup_directories():
    """Create all necessary base directories if they don't exist."""
    for directory in [
        OUTPUT_DIR, TEMP_DIR, SESSIONS_RECAP_DIR, ASSETS_BASE_DIR,
        AUDIO_OUTPUT_DIR, TEMP_TRANSCRIPTIONS, CONTEXT_DIR, PROCESSED_DIR,
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
        log.error(f"Error processing JSON in {filepath}: {e}")
        return None


def load_context_files(context_dir: Path) -> str:
    """Loads all text and markdown files from the context directory into a single string."""
    context_data = ""
    if context_dir.exists():
        all_files: set[Path] = set()
        for pattern in ("*.txt", "*.md"):
            all_files.update(context_dir.glob(pattern))

        for file_path in sorted(all_files):
            try:
                with open(file_path, "r", encoding='utf-8') as f:
                    context_data += f"--- CONTEXT FROM {file_path.name} ---\n{f.read()}\n\n"
            except Exception as e:
                log.warning(f"Error reading context file {file_path}: {e}")
    return context_data


# --- Main Processing Steps ---

def process_chat_log() -> tuple[int | None, datetime.date | None]:
    """
    Finds the newest session chat log, extracts the session number and date,
    prettifies it, and saves it to the chat log output directory.
    """
    newest_chat_log = get_newest_file(CHAT_LOG_SOURCE_DIR, "session*.json")
    if not newest_chat_log:
        log.error("No session chat log found (e.g., 'session53.json').")
        return None, None

    match = re.search(r'session(\d+)', newest_chat_log.name)
    if not match:
        log.error(f"Could not extract session number from filename: {newest_chat_log.name}")
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
        log.warning(f"Could not extract date from chat log {newest_chat_log.name}: {e}.")

    session_assets_dir = ASSETS_BASE_DIR / f"{session_number:03d}"
    session_assets_dir.mkdir(parents=True, exist_ok=True)
    output_filepath = session_assets_dir / "chat_log.json"

    if output_filepath.exists():
        log.info(f"Chat log for session {session_number} already exists in {output_filepath}. Skipping processing.")
        return session_number, session_date

    prettified_json_string = prettify_json(newest_chat_log)
    if not prettified_json_string:
        return session_number, session_date

    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write(prettified_json_string)
    log.info(f"Prettified chat log saved to: {output_filepath}")
    return session_number, session_date


def unzip_audio():
    """Unzips the newest FLAC zip file to the audio output directory."""
    if any(AUDIO_OUTPUT_DIR.glob("*.flac")):
        log.info("Audio files already exist. Skipping unzip.")
        return

    newest_zip = get_newest_file(AUDIO_SOURCE_DIR, "craig-*.flac.zip")
    if not newest_zip:
        log.warning("No matching audio zip file (craig-*.flac.zip) found.")
        return

    try:
        with zipfile.ZipFile(newest_zip, 'r') as zip_ref:
            zip_ref.extractall(AUDIO_OUTPUT_DIR)
        log.info(f"Extracted audio to: {AUDIO_OUTPUT_DIR}")

        # Clean up non-FLAC files from the extraction directory
        for item in AUDIO_OUTPUT_DIR.iterdir():
            if item.is_file() and item.suffix != ".flac":
                os.remove(item)
                log.info(f"Deleted non-FLAC file: {item.name}")

        # Move zip to _processed instead of deleting it
        dest = PROCESSED_DIR / newest_zip.name
        shutil.move(str(newest_zip), dest)
        log.info(f"Moved source zip to: {dest}")

    except zipfile.BadZipFile:
        log.error(f"{newest_zip.name} is not a valid zip file.")
    except Exception as e:
        log.error(f"An error occurred during unzipping: {e}")


class _CustomProgressBar(tqdm):
    """Custom progress bar displaying elapsed and estimated remaining time."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current = self.n
        self._start_time = time.time()
        self._last_update_time = self._start_time
        self._iteration_times: list[float] = []

    def print_in_place(self, text: str):
        sys.stdout.write("\r" + text)
        sys.stdout.flush()

    def update(self, n):
        super().update(n)
        if n <= 0:
            return
        self._current += n
        current_time = time.time()
        elapsed_time = current_time - self._start_time
        iteration_time = current_time - self._last_update_time
        self._iteration_times.append(iteration_time / n)

        if self._iteration_times:
            average_iteration_time = sum(self._iteration_times) / len(self._iteration_times)
            remaining_items = self.total - self._current
            estimated_remaining_time = remaining_items * average_iteration_time
        else:
            estimated_remaining_time = 0.0

        elapsed_time_str = time.strftime("%H:%M:%S", time.gmtime(elapsed_time))
        remaining_time_str = time.strftime("%H:%M:%S", time.gmtime(estimated_remaining_time))
        percentage = (self._current / self.total) * 100
        self.print_in_place(
            f"Progress: {percentage:.2f}% - Elapsed: {elapsed_time_str} - ETA: {remaining_time_str}"
        )
        self._last_update_time = current_time


def transcribe_audio() -> bool:
    """
    Transcribes all FLAC audio files in the audio directory using Whisper.
    Returns True if successful, False if an error occurred.
    """
    model_name = "large"
    device = "cuda"

    audio_files = sorted(AUDIO_OUTPUT_DIR.glob("*.flac"), key=os.path.getsize)
    files_to_transcribe = [
        f for f in audio_files
        if not (TEMP_TRANSCRIPTIONS / f"{f.stem}.json").exists()
    ]
    if not files_to_transcribe:
        log.info("All audio files already transcribed. Skipping.")
        return True

    # Inject custom progress bar into Whisper
    transcribe_module = sys.modules['whisper.transcribe']
    transcribe_module.tqdm.tqdm = _CustomProgressBar

    try:
        model = whisper.load_model(model_name, device=device, download_root="./models/")
    except Exception as e:
        log.error(f"Error loading Whisper model: {e}")
        log.error("Ensure you have a compatible ROCm/CUDA version installed.")
        return False

    with open(WHISPER_PROMPT_FILE, "r", encoding='utf-8') as f:
        initial_prompt = f.read().strip()

    for audio_file in tqdm(files_to_transcribe, desc="Transcribing Audio"):
        json_output_path = TEMP_TRANSCRIPTIONS / f"{audio_file.stem}.json"
        log.info(f"Transcribing {audio_file.name}...")
        try:
            result = model.transcribe(
                str(audio_file),
                language="pl",
                initial_prompt=initial_prompt,
                fp16=False,
                condition_on_previous_text=False,
                temperature=(0.0, 0.2),
                logprob_threshold=-1.0,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                word_timestamps=False,
            )
            with open(json_output_path, "w", encoding='utf-8') as f:
                json.dump(result["segments"], f, indent=2, ensure_ascii=False)
            log.info(f"Transcription of '{audio_file.name}' saved.")

        except Exception as e:
            log.error(f"CRITICAL ERROR transcribing '{audio_file.name}': {e}")
            return False

    return True


def _extract_speaker(json_file: Path, mapping: dict[str, str]) -> str:
    """
    Extracts and maps a speaker name from a Craig-bot filename.

    Expected format: <snowflake_id>-<DiscordUser>_<discriminator>.json
    Falls back gracefully at each parsing stage.
    """
    stem = json_file.stem  # e.g. "123456789-SomeUser_1234"

    parts = stem.split("-", 1)
    if len(parts) < 2:
        log.warning(
            f"Unexpected filename format '{json_file.name}' — could not split on '-'. "
            f"Using full stem as speaker name."
        )
        return stem

    raw_user_part = parts[1].lstrip("_")           # "SomeUser_1234"
    discord_user = raw_user_part.split("_")[0]      # "SomeUser"

    if not discord_user:
        log.warning(
            f"Empty discord username parsed from '{json_file.name}'. "
            f"Using raw segment '{raw_user_part}' as speaker name."
        )
        return raw_user_part or stem

    speaker = mapping.get(discord_user, discord_user)

    if discord_user not in mapping:
        log.warning(
            f"Discord user '{discord_user}' not found in mapping file. "
            f"Using raw username as speaker label."
        )

    return speaker


def combine_transcriptions(session_number: int) -> Path | None:
    """
    Combines individual JSON transcriptions into a single JSON and TXT file.
    Assigns speaker labels based on the mapping file.
    """
    session_assets_dir = ASSETS_BASE_DIR / f"{session_number:03d}"
    session_assets_dir.mkdir(parents=True, exist_ok=True)
    combined_json_path = session_assets_dir / "transcript.json"
    combined_txt_path  = session_assets_dir / "transcript.txt"

    if combined_json_path.exists() and combined_txt_path.exists():
        log.info(f"Combined transcriptions for session {session_number} already exist in {session_assets_dir}. Skipping.")
        return combined_txt_path

    try:
        with open(DISCORD_MAPPING_FILE, "r", encoding='utf-8') as f:
            discord_character_mapping: dict[str, str] = json.load(f)
    except FileNotFoundError:
        log.warning(f"Mapping file '{DISCORD_MAPPING_FILE}' not found. Using raw Discord usernames.")
        discord_character_mapping = {}

    all_segments: list[dict] = []
    json_files = sorted(TEMP_TRANSCRIPTIONS.glob("*.json"))

    for json_file in json_files:
        speaker = _extract_speaker(json_file, discord_character_mapping)

        with open(json_file, "r", encoding='utf-8') as f:
            segments: list[dict] = json.load(f)

        for segment in segments:
            text = segment['text'].strip()

            if segment.get("avg_logprob", 0) < -1.0:
                continue
            if segment.get("no_speech_prob", 0) > 0.6:
                continue
            if not text or text in {"...", "..", "."}:
                continue
            if any(phrase in text.lower() for phrase in HALLUCINATION_BLOCKLIST):
                continue
            if (
                all_segments
                and all_segments[-1]["speaker"] == speaker
                and all_segments[-1]["text"].strip() == text
            ):
                continue

            segment["speaker"] = speaker
            all_segments.append(segment)

    all_segments.sort(key=lambda x: x["start"])

    with open(combined_json_path, "w", encoding='utf-8') as f:
        json.dump(all_segments, f, indent=2, ensure_ascii=False)

    with open(combined_txt_path, "w", encoding='utf-8') as f:
        current_speaker = None
        for segment in all_segments:
            if segment["speaker"] != current_speaker:
                f.write(f"\n\n[{segment['speaker']}]\n")
                current_speaker = segment["speaker"]
            f.write(segment["text"].strip() + " ")

    log.info(f"Combined transcription saved to {combined_txt_path}")
    return combined_txt_path


# --- AI Generation and Note Creation ---

class SectionVisuals(BaseModel):
    section_title: str = Field(description="Dokładny nagłówek ### z podsumowania, do którego odnoszą się te wizualizacje.")
    images: list[str] = Field(description="Lista 2 szczegółowych promptów obrazów dla tej sekcji. Minimum 50 słów każdy, używając opisów wizualnych postaci.")
    videos: list[str] = Field(description="Lista 2 szczegółowych promptów wideo dla tej sekcji. Minimum 50 słów każdy, z ruchem kamery i dynamiką.")


class SessionData(BaseModel):
    title: str = Field(description="Tytuł sesji. Powinien być krótki, ale opisowy i chwytliwy.")
    events: list[str] = Field(description="Krótka, punktowa lista najważniejszych wydarzeń lub decyzji, które miały miejsce.")
    npcs: list[str] = Field(description="Lista najważniejszych postaci niezależnych (NPC), które pojawiły się lub odegrały kluczową rolę.")
    locations: list[str] = Field(description="Lista najważniejszych odwiedzonych lokacji.")
    items: list[str] = Field(description="Lista najważniejszych zdobytych lub użytych przedmiotów.")


class QuotesData(BaseModel):
    quotes: list[str] = Field(
        description="Lista 5-7 najbardziej pamiętnych, zabawnych lub ważnych cytatów z sesji, wraz z informacją, kto je wypowiedział. Np. 'Arevon: \"Coś tu jest nie tak.\"'."
    )


def _call_gemini_with_retry(fn, *args, max_retries: int = 3, base_delay: float = 5.0, **kwargs):
    """
    Calls a Gemini API function with exponential backoff on failure.
    Raises the last exception if all retries are exhausted.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(f"Gemini API error (attempt {attempt}/{max_retries}): {e}. Retrying in {delay:.0f}s...")
            time.sleep(delay)


def generate_session_notes(transcript_file: Path, session_number: int) -> tuple[str, SessionData, QuotesData] | None:
    """Generates a detailed summary, structured data, and quotes using the Gemini API."""
    if not GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY not set in .env file. Skipping note generation.")
        return None

    genai.configure(api_key=GEMINI_API_KEY)

    # Temporary files for interim results
    summary_file = TEMP_DIR / f"summary_session_{session_number}.txt"
    details_file = TEMP_DIR / f"details_session_{session_number}.json"
    quotes_file = TEMP_DIR / f"quotes_session_{session_number}.json"

    with open(transcript_file, "r", encoding='utf-8') as f:
        transcript_content = f.read()

    # --- Step 1: Generate Detailed Summary ---
    if summary_file.exists():
        log.info(f"Existing session summary found at {summary_file}. Loading it...")
        with open(summary_file, "r", encoding='utf-8') as f:
            session_summary = f.read()
    else:
        with open(SUMMARY_PROMPT_FILE, "r", encoding='utf-8') as f:
            summary_prompt = f.read()

        summary_model = genai.GenerativeModel(
            model_name=GEMINI_PRO_MODEL,
            system_instruction=summary_prompt,
        )

        summary_messages = []

        general_context = load_context_files(CONTEXT_DIR)
        if general_context:
            summary_messages.append({"role": "user", "parts": [f"DODATKOWY KONTEKST KAMPANII:\n{general_context}\n\n---\n\n"]})
        summary_messages.append({"role": "user", "parts": [f"TRANSKRYPT OBECNEJ SESJI:\n{transcript_content}"]})

        log.info("Generating detailed session summary...")
        try:
            summary_response = _call_gemini_with_retry(
                summary_model.generate_content,
                summary_messages,
                generation_config=genai.GenerationConfig(temperature=1),
            )
        except Exception as e:
            log.error(f"Failed to generate session summary after retries: {e}")
            return None

        session_summary: str = summary_response.text
        log.info("Session summary generated.")
        
        # Save interim summary
        with open(summary_file, "w", encoding='utf-8') as f:
            f.write(session_summary)
        log.info(f"Interim session summary saved to {summary_file}")

    # --- Step 2: Extract Structured Details ---
    if details_file.exists():
        log.info(f"Existing session details found at {details_file}. Loading it...")
        try:
            with open(details_file, "r", encoding='utf-8') as f:
                session_data = SessionData.model_validate_json(f.read())
        except Exception as e:
            log.warning(f"Failed to load existing details from {details_file}: {e}. Re-generating.")
            session_data = None
    else:
        session_data = None

    if not session_data:
        log.info(f"Waiting {GEMINI_API_SLEEP_SECS}s for API rate limit...")
        time.sleep(GEMINI_API_SLEEP_SECS)

        with open(DETAILS_PROMPT_FILE, "r", encoding='utf-8') as f:
            details_prompt = f.read()

        details_client = instructor.from_gemini(
            client=genai.GenerativeModel(
                model_name=GEMINI_FLASH_MODEL,
                system_instruction=details_prompt,
            ),
            mode=instructor.Mode.GEMINI_JSON,
        )

        log.info("Extracting structured details...")
        try:
            session_data: SessionData = details_client.chat.completions.create(
                messages=[{"role": "user", "content": f"PODSUMOWANIE SESJI:\n{session_summary}"}],
                response_model=SessionData,
                max_retries=3,
            )
        except Exception as e:
            log.error(f"Failed to extract structured details: {e}")
            return None
        log.info("Session details extracted.")
        
        # Save interim details
        with open(details_file, "w", encoding='utf-8') as f:
            f.write(session_data.model_dump_json(indent=2))
        log.info(f"Interim session details saved to {details_file}")

    # --- Step 3: Extract Quotes ---
    if quotes_file.exists():
        log.info(f"Existing quotes found at {quotes_file}. Loading it...")
        try:
            with open(quotes_file, "r", encoding='utf-8') as f:
                quotes_data = QuotesData.model_validate_json(f.read())
        except Exception as e:
            log.warning(f"Failed to load existing quotes from {quotes_file}: {e}. Re-generating.")
            quotes_data = None
    else:
        quotes_data = None

    if not quotes_data:
        log.info(f"Waiting {GEMINI_API_SLEEP_SECS}s for API rate limit...")
        time.sleep(GEMINI_API_SLEEP_SECS)

        with open(QUOTES_PROMPT_FILE, "r", encoding='utf-8') as f:
            quotes_prompt = f.read()

        quotes_client = instructor.from_gemini(
            client=genai.GenerativeModel(
                model_name=GEMINI_FLASH_MODEL,
                system_instruction=quotes_prompt,
            ),
            mode=instructor.Mode.GEMINI_JSON,
        )

        log.info("Extracting memorable quotes...")
        try:
            quotes_data: QuotesData = quotes_client.chat.completions.create(
                messages=[{"role": "user", "content": f"PEŁNA TRANSKRYPCJA:\n{transcript_content}"}],
                response_model=QuotesData,
                max_retries=3,
            )
        except Exception as e:
            log.error(f"Failed to extract quotes: {e}")
            return None
        log.info("Quotes extracted.")
        
        # Save interim quotes
        with open(quotes_file, "w", encoding='utf-8') as f:
            f.write(quotes_data.model_dump_json(indent=2))
        log.info(f"Interim quotes saved to {quotes_file}")

    return session_summary, session_data, quotes_data


def save_summary_file(
    session_summary: str,
    session_data: SessionData,
    quotes_data: QuotesData,
    session_number: int,
    session_date: datetime.date,
):
    """Saves the generated notes to a formatted Markdown file."""
    with open(TEMPLATE_FILE, "r", encoding='utf-8') as f:
        raw_template = f.read()

    # Use string.Template ($variable syntax) to avoid crashes when the
    # AI-generated summary contains literal { } characters (e.g. JSON, code blocks).
    template = Template(raw_template)
    output = template.safe_substitute(
        number=session_number,
        padded_number=f"{session_number:03d}",
        title=session_data.title,
        date=session_date.strftime("%d.%m.%Y"),
        summary=session_summary,
        events="\n".join(f"* {event}" for event in session_data.events),
        npcs="\n".join(f"* {npc}"   for npc   in session_data.npcs),
        locations="\n".join(f"* {loc}"  for loc   in session_data.locations),
        items="\n".join(f"* {item}" for item  in session_data.items),
        quotes="\n".join(f"* {quote}" for quote in quotes_data.quotes),
    )

    sane_title = re.sub(r'[\\/*?:"<>|]', "", session_data.title)
    output_file = SESSIONS_RECAP_DIR / f"Sesja {session_number} - {sane_title}.md"

    with open(output_file, "w", encoding='utf-8') as f:
        f.write(output)
    log.info(f"Session notes saved to {output_file}")


# --- Workflow Functions ---

def run_transcription_workflow() -> tuple[Path, int, datetime.date] | None:
    """Runs the workflow up to and including combining transcriptions."""
    start_time = time.time()

    log.info("\n[Step 1/4] Processing Chat Log...")
    session_number, session_date = process_chat_log()
    if session_number is None:
        log.error("Error processing chat log. Aborting workflow.")
        return None

    if session_date is None:
        today = datetime.date.today()
        session_date = today - datetime.timedelta(days=today.weekday())
        log.warning(f"Could not determine date. Defaulting to last Monday: {session_date.strftime('%Y-%m-%d')}")

    log.info(f"✅ Found Session Number: {session_number}")
    log.info(f"✅ Found Session Date: {session_date.strftime('%Y-%m-%d')}")

    log.info("\n[Step 2/4] Preparing Audio Files...")
    unzip_audio()
    log.info("✅ Audio files are ready.")

    log.info("\n[Step 3/4] Transcribing Audio...")
    if not transcribe_audio():
        log.error("Transcription failed. Aborting workflow to prevent incomplete data.")
        return None
    log.info("✅ Transcription complete.")

    log.info("\n[Step 4/4] Combining Transcriptions...")
    transcript_file = combine_transcriptions(session_number)
    if not transcript_file:
        log.error("Error combining transcriptions. Aborting workflow.")
        return None
    log.info("✅ Transcriptions combined.")

    elapsed = time.strftime('%H:%M:%S', time.gmtime(time.time() - start_time))
    log.info(f"\n✨ Transcription workflow completed in {elapsed}. ✨")
    return transcript_file, session_number, session_date


def run_full_workflow():
    """Runs the entire workflow, including AI generation."""
    start_time = time.time()

    transcription_result = run_transcription_workflow()
    if not transcription_result:
        return

    transcript_file, session_number, session_date = transcription_result

    log.info("\n[Step 5/5] Generating Session Notes with AI...")
    notes = generate_session_notes(transcript_file, session_number)
    if notes:
        summary, details, quotes = notes
        save_summary_file(summary, details, quotes, session_number, session_date)
        log.info("✅ AI-powered session notes have been generated and saved.")
    else:
        log.warning("⚠️ AI note generation was skipped or failed.")

    elapsed = time.strftime('%H:%M:%S', time.gmtime(time.time() - start_time))
    log.info(f"\n✨ Full workflow completed in {elapsed}. ✨")


def run_manual_workflow():
    """Handles the workflow for manually entering session notes."""
    log.info("\n--- Manual Entry Workflow ---")

    log.info("\n[Step 1/4] Reading session info from the latest chat log...")
    session_number, session_date = process_chat_log()
    if session_number is None:
        log.error("Error processing chat log. Cannot proceed without a session number. Aborting.")
        return

    if session_date is None:
        today = datetime.date.today()
        session_date = today - datetime.timedelta(days=today.weekday())
        log.warning(f"Could not determine date from chat log. Defaulting to last Monday: {session_date.strftime('%Y-%m-%d')}")

    log.info(f"✅ Found Session Number: {session_number}")
    log.info(f"✅ Found Session Date: {session_date.strftime('%Y-%m-%d')}")

    print("\n[Step 2/4] Enter the session summary.")
    print("Paste your summary below. Press Ctrl+D to finish.")
    session_summary = sys.stdin.read().strip()
    if not session_summary:
        log.error("Summary is empty. Aborting.")
        return
    log.info("✅ Summary received.")

    print("\n[Step 3/4] Enter the session details as JSON.")
    print("Paste the JSON data below. Press Ctrl+D to finish.")

    session_data: SessionData | None = None
    while session_data is None:
        try:
            sys.stdin = open('/dev/tty')
            json_input = sys.stdin.read().strip()
            if not json_input:
                log.error("JSON input is empty. Aborting.")
                return
            session_data = SessionData.model_validate_json(json_input)
            log.info("✅ Session details JSON is valid.")
        except (json.JSONDecodeError, ValidationError) as e:
            log.error(f"Data is invalid: {e}")
            choice = input("Would you like to try again? [y/n]: ").lower()
            if choice not in ['y', 'yes']:
                log.info("Aborting.")
                return
            print("Please paste the JSON data again:")

    print("\n[Step 4/4] Enter the quotes as JSON.")
    print("Paste the JSON data below. Press Ctrl+D to finish.")

    quotes_data: QuotesData | None = None
    while quotes_data is None:
        try:
            sys.stdin = open('/dev/tty')
            json_input = sys.stdin.read().strip()
            if not json_input:
                log.error("JSON input is empty. Aborting.")
                return
            quotes_data = QuotesData.model_validate_json(json_input)
            log.info("✅ Quotes JSON is valid.")
        except (json.JSONDecodeError, ValidationError) as e:
            log.error(f"Data is invalid: {e}")
            choice = input("Would you like to try again? [y/n]: ").lower()
            if choice not in ['y', 'yes']:
                log.info("Aborting.")
                return
            print("Please paste the JSON data again:")

    save_summary_file(session_summary, session_data, quotes_data, session_number, session_date)
    log.info("\n✨ Manual entry workflow completed successfully. ✨")


# --- Main Orchestration ---

def handle_temp_directory():
    """Checks for an existing temp directory and asks the user how to proceed."""
    if TEMP_DIR.exists() and any(TEMP_DIR.iterdir()):
        print("-" * 50)
        print(f"⚠️  Warning: Temporary directory '{TEMP_DIR}' already contains files.")
        print("Continuing will reuse existing transcriptions and interim AI-generated notes if they exist.")

        while True:
            choice = input("Do you want to delete the existing temporary directory? [y/n]: ").lower().strip()
            if choice in ['y', 'yes']:
                try:
                    shutil.rmtree(TEMP_DIR)
                    log.info(f"Temporary directory '{TEMP_DIR}' has been removed.")
                except Exception as e:
                    log.error(f"Error removing temporary directory: {e}")
                    log.error("Please remove it manually and restart the script.")
                    sys.exit(1)
                break
            elif choice in ['n', 'no']:
                log.info("Continuing with existing temporary files.")
                break
            else:
                print("Invalid choice. Please enter 'y' or 'n'.")
        print("-" * 50)


def display_menu() -> str:
    """Displays the main menu and handles user input."""
    print("\n" + "=" * 50)
    print("🚀 D&D Session Processing Workflow 🚀")
    print("=" * 50)
    print("Please choose an option:")
    print("  [1] Start Full Workflow (Transcribe -> Generate AI Notes)")
    print("  [2] Run Workflow until Transcribing (Generate transcript file only)")
    print("  [3] Manual Note Entry (from existing summary/details)")
    print("  [4] Exit")
    print("=" * 50)

    while True:
        choice = input("Enter your choice [1-4]: ").strip()
        if choice in ['1', '2', '3', '4']:
            return choice
        print("❌ Invalid choice. Please enter a number from 1 to 4.")


def main():
    """Main function to orchestrate the entire workflow via a menu."""
    handle_temp_directory()
    setup_directories()

    while True:
        choice = display_menu()
        if choice == '1':
            log.info("\nStarting Full Workflow...")
            run_full_workflow()
        elif choice == '2':
            log.info("\nStarting Transcription-Only Workflow...")
            run_transcription_workflow()
        elif choice == '3':
            log.info("\nStarting Manual Entry Workflow...")
            run_manual_workflow()
        elif choice == '4':
            log.info("\n👋 Exiting. Goodbye!")
            break


if __name__ == "__main__":
    main()
