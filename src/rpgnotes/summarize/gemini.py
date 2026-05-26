from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import google.generativeai as genai
import instructor

from ..helpers import load_context_files
from .models import QuotesData, SessionData

log = logging.getLogger("rpgnotes")

T = TypeVar("T")


def _call_with_retry(
    fn: Callable[..., T],
    *args: object,
    max_retries: int = 3,
    base_delay: float = 5.0,
    **kwargs: object,
) -> T:
    """Call `fn` with exponential backoff. Raises the last exception on exhaustion."""
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "Gemini API error (attempt %d/%d): %s. Retrying in %.0fs…",
                attempt,
                max_retries,
                e,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError("unreachable")


def generate_summary(
    *,
    transcript_content: str,
    summary_prompt: str,
    model_name: str,
    context_dir: Path,
    cache_file: Path,
) -> str:
    """Generate the narrative summary. Reads from `cache_file` if present."""
    if cache_file.exists():
        log.info("Existing session summary found at %s. Loading it…", cache_file)
        return cache_file.read_text(encoding="utf-8")

    summary_model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=summary_prompt,
    )

    messages: list[dict[str, object]] = []
    general_context = load_context_files(context_dir)
    if general_context:
        messages.append(
            {"role": "user", "parts": [f"DODATKOWY KONTEKST KAMPANII:\n{general_context}\n\n---\n\n"]}
        )
    messages.append({"role": "user", "parts": [f"TRANSKRYPT OBECNEJ SESJI:\n{transcript_content}"]})

    log.info("Generating detailed session summary…")
    response = _call_with_retry(
        summary_model.generate_content,
        messages,
        generation_config=genai.GenerationConfig(temperature=1),
    )
    text: str = response.text
    log.info("Session summary generated.")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(text, encoding="utf-8")
    log.info("Interim session summary saved to %s", cache_file)
    return text


def generate_details(
    *,
    session_summary: str,
    details_prompt: str,
    model_name: str,
    cache_file: Path,
) -> SessionData:
    """Extract structured `SessionData` from the summary. Reads from `cache_file` if present."""
    if cache_file.exists():
        log.info("Existing session details found at %s. Loading it…", cache_file)
        try:
            return SessionData.model_validate_json(cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to load existing details from %s: %s. Re-generating.", cache_file, e)

    client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=model_name,
            system_instruction=details_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    log.info("Extracting structured details…")
    data: SessionData = client.chat.completions.create(
        messages=[{"role": "user", "content": f"PODSUMOWANIE SESJI:\n{session_summary}"}],
        response_model=SessionData,
        max_retries=3,
    )
    log.info("Session details extracted.")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    log.info("Interim session details saved to %s", cache_file)
    return data


def generate_quotes(
    *,
    transcript_content: str,
    quotes_prompt: str,
    model_name: str,
    cache_file: Path,
) -> QuotesData:
    """Extract memorable quotes from the transcript. Reads from `cache_file` if present."""
    if cache_file.exists():
        log.info("Existing quotes found at %s. Loading it…", cache_file)
        try:
            return QuotesData.model_validate_json(cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to load existing quotes from %s: %s. Re-generating.", cache_file, e)

    client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=model_name,
            system_instruction=quotes_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    log.info("Extracting memorable quotes…")
    data: QuotesData = client.chat.completions.create(
        messages=[{"role": "user", "content": f"PEŁNA TRANSKRYPCJA:\n{transcript_content}"}],
        response_model=QuotesData,
        max_retries=3,
    )
    log.info("Quotes extracted.")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    log.info("Interim quotes saved to %s", cache_file)
    return data
