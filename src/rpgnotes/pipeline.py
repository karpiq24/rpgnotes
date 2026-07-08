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

from .audio import extract_recording_start, unzip_audio
from .chatevents import ChatEvent, extract_chat_events, write_chat_events
from .chatlog import process_chat_log
from .config import Settings
from .enrich import build_enriched_transcript
from .summarize import (
    QuotesData,
    SessionData,
    build_session_glossary,
    generate_quotes,
    generate_summary_chunked,
    validate_summary,
    verify_quotes,
)
from .template import save_summary_file
from .transcribe import combine_transcriptions, transcribe_audio_dir
from .transcribe.faster import FasterWhisperTranscriber
from .visual import VisualEntry, caption_screenshots

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
    session_assets_dir = settings.assets_base_dir / f"{session_number:03d}"
    _save_recording_start(settings, session_assets_dir)
    unzip_audio(settings.downloads_dir, settings.audio_output_dir, settings.processed_dir)
    log.info("✅ Audio files are ready.")
    _save_chat_events(session_assets_dir)

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


def _save_recording_start(settings: Settings, session_assets_dir: Path) -> None:
    """Persist the Craig recording start (unix ts) as `recording_start.txt`.

    This is the shared t=0 anchor for transcript offsets, `[VISUAL]` lines and
    chat events. Best-effort: any failure only logs a warning.
    """
    anchor_file = session_assets_dir / "recording_start.txt"
    if anchor_file.exists():
        return
    started = extract_recording_start(settings.downloads_dir, settings.processed_dir)
    if started is None:
        return
    session_assets_dir.mkdir(parents=True, exist_ok=True)
    anchor_file.write_text(f"{started}\n", encoding="utf-8")
    log.info("Recording start %d saved to %s", started, anchor_file)


def _load_recording_start(session_assets_dir: Path) -> int | None:
    anchor_file = session_assets_dir / "recording_start.txt"
    if not anchor_file.exists():
        return None
    try:
        return int(anchor_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as e:
        log.warning("Could not read %s: %s", anchor_file, e)
        return None


def _save_chat_events(session_assets_dir: Path) -> None:
    """Distill `chat_log.json` into timeline-anchored `chat_events.{json,txt}`.

    Best-effort and resumable: skipped when the output already exists, and any
    failure only logs a warning.
    """
    chat_log_file = session_assets_dir / "chat_log.json"
    events_json = session_assets_dir / "chat_events.json"
    if events_json.exists():
        log.info("Chat events already exist at %s. Skipping.", events_json)
        return
    if not chat_log_file.exists():
        log.warning("No chat_log.json in %s — skipping chat events.", session_assets_dir)
        return
    try:
        events = extract_chat_events(chat_log_file, _load_recording_start(session_assets_dir))
        write_chat_events(events, events_json, session_assets_dir / "chat_events.txt")
    except Exception as e:
        log.warning("Chat event extraction failed: %s. Continuing without chat events.", e)


def _load_chat_events(session_assets_dir: Path) -> list[ChatEvent]:
    """Parse `chat_events.json` back into `ChatEvent`s. Best-effort: [] on any failure."""
    events_file = session_assets_dir / "chat_events.json"
    if not events_file.exists():
        return []
    try:
        raw = json.loads(events_file.read_text(encoding="utf-8"))
        return [ChatEvent.model_validate(item) for item in raw]
    except Exception as e:
        log.warning("Could not load chat events from %s: %s", events_file, e)
        return []


def _caption_session_screenshots(
    settings: Settings,
    session_assets_dir: Path,
    glossary: str,
    session_number: int,
) -> list[VisualEntry]:
    """Caption screenshots when SCREENSHOTS_DIR is configured. Best-effort: [] otherwise."""
    screenshots_dir = settings.resolved_screenshots_dir
    if screenshots_dir is None:
        return []
    if not screenshots_dir.is_dir():
        log.warning("SCREENSHOTS_DIR %s does not exist. Skipping visual context.", screenshots_dir)
        return []
    try:
        return caption_screenshots(
            screenshots_dir=screenshots_dir,
            caption_prompt=settings.visual_caption_prompt_file.read_text(encoding="utf-8"),
            glossary=glossary,
            model_name=settings.resolved_visual_caption_model,
            temp_dir=settings.temp_dir,
            session_number=session_number,
            visual_log_file=session_assets_dir / "visual_log.json",
            dedupe=settings.visual_dedupe,
            api_sleep_secs=settings.gemini_api_sleep_secs,
            upload_max_dim=settings.visual_upload_max_dim,
            upload_jpeg_quality=settings.visual_upload_jpeg_quality,
            crop=settings.visual_crop,
            recording_start=_load_recording_start(session_assets_dir),
        )
    except Exception as e:
        log.warning("Visual context failed: %s. Continuing without screenshots.", e)
        return []


def _apply_enrichment(
    settings: Settings,
    session_assets_dir: Path,
    transcript_content: str,
    glossary: str,
    session_number: int,
) -> str:
    """Merge `[VISUAL]` captions and `[CZAT]` chat events into one enriched transcript.

    Returns the time-sorted enriched transcript (cached at
    `transcript_enriched.txt`, so the step is resumable) when at least one
    annotation source exists; with neither screenshots nor chat events the
    plain transcript is returned unchanged and no file is written.
    Best-effort: any failure logs a warning and never fails the pipeline.
    """
    enriched_file = session_assets_dir / "transcript_enriched.txt"
    if enriched_file.exists():
        log.info("Existing enriched transcript found at %s. Loading it…", enriched_file)
        return enriched_file.read_text(encoding="utf-8")

    entries = _caption_session_screenshots(settings, session_assets_dir, glossary, session_number)
    chat_events = _load_chat_events(session_assets_dir)
    if not entries and not chat_events:
        return transcript_content

    try:
        segments = json.loads(
            (session_assets_dir / "transcript.json").read_text(encoding="utf-8")
        )
        enriched = build_enriched_transcript(segments, entries, chat_events)
    except Exception as e:
        log.warning("Transcript enrichment failed: %s. Continuing with the plain transcript.", e)
        return transcript_content

    enriched_file.write_text(enriched, encoding="utf-8")
    log.info(
        "Enriched transcript with %d [VISUAL] and %d [CZAT] anchor(s) saved to %s",
        len(entries),
        len(chat_events),
        enriched_file,
    )
    return enriched


def _generate_notes(
    settings: Settings,
    transcript_file: Path,
    session_number: int,
) -> tuple[str, QuotesData] | None:
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY not set. Skipping note generation.")
        return None

    genai.configure(api_key=settings.gemini_api_key)
    plain_transcript = transcript_file.read_text(encoding="utf-8")

    summary_cache = settings.temp_dir / f"summary_session_{session_number}.txt"
    validated_cache = settings.temp_dir / f"validated_summary_session_{session_number}.txt"
    quotes_cache = settings.temp_dir / f"quotes_session_{session_number}.json"

    session_assets_dir = settings.assets_base_dir / f"{session_number:03d}"
    draft_file = session_assets_dir / "draft0.md"
    report_file = session_assets_dir / "validation_report.md"

    glossary = build_session_glossary(
        context_dir=settings.context_dir,
        phonetic_corrections_file=settings.phonetic_corrections_file,
        transcript_content=plain_transcript,
    )

    # Summary generation and validation see the enriched transcript ([VISUAL]
    # + [CZAT] anchors); quote extraction/verification stays on the plain one
    # so quote candidates are always actually spoken lines.
    transcript_content = _apply_enrichment(
        settings, session_assets_dir, plain_transcript, glossary, session_number
    )

    try:
        summary, _rolling_summaries = generate_summary_chunked(
            transcript_content=transcript_content,
            style_rules=settings.style_rules_file.read_text(encoding="utf-8"),
            anti_hallucination=settings.anti_hallucination_file.read_text(encoding="utf-8"),
            glossary=glossary,
            model_name=settings.gemini_pro_model,
            context_dir=settings.context_dir,
            temp_dir=settings.temp_dir,
            session_number=session_number,
            cache_file=summary_cache,
            chunk_lines=settings.summary_chunk_lines,
            temperature=settings.summary_temperature,
            polish_pass=settings.summary_polish_pass,
            polish_temperature=settings.summary_polish_temperature,
            timeline_recent_sessions=settings.timeline_recent_sessions,
        )
    except Exception as e:
        log.error("Failed to generate session summary after retries: %s", e)
        return None

    if validated_cache.exists():
        log.info("Existing validated summary found at %s. Loading it…", validated_cache)
        summary = validated_cache.read_text(encoding="utf-8")
    else:
        log.info("Waiting %.0fs for API rate limit…", settings.gemini_api_sleep_secs)
        time.sleep(settings.gemini_api_sleep_secs)
        try:
            summary, _report = validate_summary(
                summary=summary,
                transcript_content=transcript_content,
                validation_prompt=settings.validation_prompt_file.read_text(encoding="utf-8"),
                model_name=settings.gemini_pro_model,
                report_file=report_file,
            )
            validated_cache.write_text(summary, encoding="utf-8")
        except Exception as e:
            log.error("Summary validation failed: %s. Continuing with the unvalidated draft.", e)

    session_assets_dir.mkdir(parents=True, exist_ok=True)
    draft_file.write_text(summary, encoding="utf-8")
    log.info("Validated summary draft saved to %s", draft_file)

    if not quotes_cache.exists():
        log.info("Waiting %.0fs for API rate limit…", settings.gemini_api_sleep_secs)
        time.sleep(settings.gemini_api_sleep_secs)
    try:
        quotes = generate_quotes(
            transcript_content=plain_transcript,
            quotes_prompt=settings.quotes_prompt_file.read_text(encoding="utf-8"),
            model_name=settings.gemini_flash_model,
            cache_file=quotes_cache,
        )
    except Exception as e:
        log.error("Failed to extract quotes: %s", e)
        return None
    quotes = verify_quotes(quotes, plain_transcript)
    (session_assets_dir / "quotes.json").write_text(
        quotes.model_dump_json(indent=2), encoding="utf-8"
    )

    return summary, quotes


def run_full_workflow(settings: Settings) -> None:
    start = time.time()
    result = run_transcription_workflow(settings)
    if not result:
        return
    transcript_file, session_number, _session_date = result

    log.info("\n[Step 5/5] Generating Session Notes with AI…")
    notes = _generate_notes(settings, transcript_file, session_number)
    if notes:
        # The deliverable is draft0.md plus quotes.json etc., all written
        # straight into OUTPUT_DIR/assets/sessions/<NNN>/ — the final session
        # note is assembled in OotD after the refine pass, reading from there.
        log.info("✅ AI-generated draft and quotes are ready in %s.", settings.assets_base_dir)
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
