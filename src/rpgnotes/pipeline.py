from __future__ import annotations

import datetime as _dt
import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import TypeVar

import google.generativeai as genai
from pydantic import BaseModel, ValidationError

from .audio import unzip_audio
from .chatlog import process_chat_log
from .config import Settings
from .summarize import (
    QuotesData,
    SessionData,
    generate_details,
    generate_quotes,
    generate_summary,
)
from .template import save_summary_file
from .transcribe import combine_transcriptions, transcribe_audio_dir
from .transcribe.faster import FasterWhisperTranscriber

log = logging.getLogger("rpgnotes")

_Model = TypeVar("_Model", bound=BaseModel)


def _fallback_session_date() -> _dt.date:
    today = _dt.date.today()
    return today - _dt.timedelta(days=today.weekday())


def _build_transcriber(settings: Settings) -> FasterWhisperTranscriber:
    initial_prompt = settings.whisper_prompt_file.read_text(encoding="utf-8").strip()
    return FasterWhisperTranscriber(
        model_size=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        download_root=settings.whisper_cache_dir,
        initial_prompt=initial_prompt,
        language=settings.whisper_language,
        vad_filter=settings.whisper_vad,
    )


def run_transcription_workflow(settings: Settings) -> tuple[Path, int, _dt.date] | None:
    """Steps 1-4: chat log → unzip → transcribe → combine."""
    start = time.time()

    log.info("\n[Step 1/4] Processing Chat Log…")
    session_number, session_date = process_chat_log(settings.downloads_dir, settings.assets_base_dir)
    if session_number is None:
        log.error("Error processing chat log. Aborting workflow.")
        return None
    if session_date is None:
        session_date = _fallback_session_date()
        log.warning("Could not determine date. Defaulting to last Monday: %s", session_date)
    log.info("✅ Session %d on %s", session_number, session_date)

    log.info("\n[Step 2/4] Preparing Audio Files…")
    unzip_audio(settings.downloads_dir, settings.audio_output_dir, settings.processed_dir)
    log.info("✅ Audio files are ready.")

    log.info("\n[Step 3/4] Transcribing Audio…")
    ok = transcribe_audio_dir(
        settings.audio_output_dir,
        settings.temp_transcriptions_dir,
        lambda: _build_transcriber(settings),
    )
    if not ok:
        log.error("Transcription failed. Aborting workflow.")
        return None
    log.info("✅ Transcription complete.")

    log.info("\n[Step 4/4] Combining Transcriptions…")
    transcript_file = combine_transcriptions(
        session_number,
        settings.temp_transcriptions_dir,
        settings.assets_base_dir,
        settings.discord_mapping_file,
    )
    if not transcript_file:
        log.error("Error combining transcriptions. Aborting workflow.")
        return None
    log.info("✅ Transcriptions combined.")

    elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - start))
    log.info("\n✨ Transcription workflow completed in %s. ✨", elapsed)
    return transcript_file, session_number, session_date


def _generate_notes(
    settings: Settings,
    transcript_file: Path,
    session_number: int,
) -> tuple[str, SessionData, QuotesData] | None:
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY not set. Skipping note generation.")
        return None

    genai.configure(api_key=settings.gemini_api_key)
    transcript_content = transcript_file.read_text(encoding="utf-8")

    summary_cache = settings.temp_dir / f"summary_session_{session_number}.txt"
    details_cache = settings.temp_dir / f"details_session_{session_number}.json"
    quotes_cache = settings.temp_dir / f"quotes_session_{session_number}.json"

    try:
        summary = generate_summary(
            transcript_content=transcript_content,
            summary_prompt=settings.summary_prompt_file.read_text(encoding="utf-8"),
            model_name=settings.gemini_pro_model,
            context_dir=settings.context_dir,
            cache_file=summary_cache,
        )
    except Exception as e:
        log.error("Failed to generate session summary after retries: %s", e)
        return None

    if not details_cache.exists():
        log.info("Waiting %.0fs for API rate limit…", settings.gemini_api_sleep_secs)
        time.sleep(settings.gemini_api_sleep_secs)
    try:
        details = generate_details(
            session_summary=summary,
            details_prompt=settings.details_prompt_file.read_text(encoding="utf-8"),
            model_name=settings.gemini_flash_model,
            cache_file=details_cache,
        )
    except Exception as e:
        log.error("Failed to extract structured details: %s", e)
        return None

    if not quotes_cache.exists():
        log.info("Waiting %.0fs for API rate limit…", settings.gemini_api_sleep_secs)
        time.sleep(settings.gemini_api_sleep_secs)
    try:
        quotes = generate_quotes(
            transcript_content=transcript_content,
            quotes_prompt=settings.quotes_prompt_file.read_text(encoding="utf-8"),
            model_name=settings.gemini_flash_model,
            cache_file=quotes_cache,
        )
    except Exception as e:
        log.error("Failed to extract quotes: %s", e)
        return None

    return summary, details, quotes


def run_full_workflow(settings: Settings) -> None:
    start = time.time()
    result = run_transcription_workflow(settings)
    if not result:
        return
    transcript_file, session_number, session_date = result

    log.info("\n[Step 5/5] Generating Session Notes with AI…")
    notes = _generate_notes(settings, transcript_file, session_number)
    if notes:
        summary, details, quotes = notes
        save_summary_file(
            settings.template_file,
            settings.sessions_recap_dir,
            summary,
            details,
            quotes,
            session_number,
            session_date,
        )
        log.info("✅ AI-powered session notes have been generated and saved.")
    else:
        log.warning("⚠️ AI note generation was skipped or failed.")

    elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - start))
    log.info("\n✨ Full workflow completed in %s. ✨", elapsed)


def run_manual_workflow(settings: Settings) -> None:
    log.info("\n--- Manual Entry Workflow ---")

    session_number, session_date = process_chat_log(settings.downloads_dir, settings.assets_base_dir)
    if session_number is None:
        log.error("Error processing chat log. Aborting.")
        return
    if session_date is None:
        session_date = _fallback_session_date()
        log.warning("Could not determine date. Defaulting to last Monday: %s", session_date)
    log.info("✅ Session %d on %s", session_number, session_date)

    print("\n[Step 2/4] Paste the session summary. Press Ctrl+D when done.")
    session_summary = sys.stdin.read().strip()
    if not session_summary:
        log.error("Summary is empty. Aborting.")
        return
    log.info("✅ Summary received.")

    session_data = _prompt_json(SessionData, label="session details")
    if not session_data:
        return
    quotes_data = _prompt_json(QuotesData, label="quotes")
    if not quotes_data:
        return

    save_summary_file(
        settings.template_file,
        settings.sessions_recap_dir,
        session_summary,
        session_data,
        quotes_data,
        session_number,
        session_date,
    )
    log.info("\n✨ Manual entry workflow completed successfully. ✨")


def _prompt_json(model_cls: type[_Model], label: str) -> _Model | None:
    print(f"\nPaste the {label} JSON below. Press Ctrl+D when done.")
    while True:
        try:
            sys.stdin = open("/dev/tty")  # noqa: SIM115 — must outlive this scope
            raw = sys.stdin.read().strip()
            if not raw:
                log.error("%s JSON is empty. Aborting.", label)
                return None
            return model_cls.model_validate_json(raw)
        except (json.JSONDecodeError, ValidationError) as e:
            log.error("Data is invalid: %s", e)
            choice = input("Try again? [y/n]: ").lower()
            if choice not in {"y", "yes"}:
                log.info("Aborting.")
                return None
            print("Paste the JSON again:")


def handle_temp_directory(settings: Settings, *, interactive: bool) -> None:
    """If `interactive`, ask whether to wipe a non-empty temp dir; otherwise no-op."""
    if not (settings.temp_dir.exists() and any(settings.temp_dir.iterdir())):
        return
    if not interactive:
        log.info("Reusing existing temporary files in %s.", settings.temp_dir)
        return

    print("-" * 50)
    print(f"⚠️  Warning: Temporary directory '{settings.temp_dir}' already contains files.")
    print("Continuing will reuse existing transcriptions and interim AI-generated notes.")
    while True:
        choice = input("Delete the existing temporary directory? [y/n]: ").lower().strip()
        if choice in {"y", "yes"}:
            try:
                shutil.rmtree(settings.temp_dir)
                log.info("Temporary directory '%s' has been removed.", settings.temp_dir)
            except OSError as e:
                log.error("Error removing temporary directory: %s. Remove manually.", e)
                sys.exit(1)
            break
        if choice in {"n", "no"}:
            log.info("Continuing with existing temporary files.")
            break
        print("Invalid choice. Enter 'y' or 'n'.")
    print("-" * 50)
