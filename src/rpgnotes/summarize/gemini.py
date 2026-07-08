from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import google.generativeai as genai
import instructor

from ..helpers import load_context_files
from .chunker import split_transcript
from .models import Finding, QuotesData, ValidationReport

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
    temperature: float = 0.3,
) -> str:
    """Legacy one-shot narrative summary. Reads from `cache_file` if present.

    The default pipeline uses `generate_summary_chunked` instead; this stays
    for the manual/legacy path.
    """
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
        generation_config=genai.GenerationConfig(temperature=temperature),
    )
    text: str = response.text
    log.info("Session summary generated.")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(text, encoding="utf-8")
    log.info("Interim session summary saved to %s", cache_file)
    return text


_NARRATIVE_RE = re.compile(
    r"NARRATIVE:?\s*\n(?P<body>.*?)(?=\n\s*ROLLING_SUMMARY|\Z)", re.DOTALL
)
_ROLLING_RE = re.compile(r"ROLLING_SUMMARY:?\s*\n(?P<body>.*)\Z", re.DOTALL)

_CHUNK_INSTRUCTIONS = """
# Zadanie: podsumowanie FRAGMENTU sesji

Dostajesz jeden fragment transkrypcji (sesja jest przetwarzana po kolei,
fragment po fragmencie) oraz ROLLING_SUMMARY — skrót tego, co wydarzyło się
we wcześniejszych fragmentach. Podsumuj TYLKO bieżący fragment; ROLLING_SUMMARY
służy wyłącznie jako kontekst (nie opisuj ponownie tych wydarzeń).

Zachowuj ściśle chronologię wydarzeń wewnątrz fragmentu — nigdy nie zmieniaj
ich kolejności.

Odpowiedz DOKŁADNIE w tym formacie (bez żadnego innego tekstu):

NARRATIVE:
<1-4 sekcje `###` z akapitami, zgodnie z zasadami stylu>

ROLLING_SUMMARY:
<3-5 punktów podsumowujących stan fabuły PO tym fragmencie — kto gdzie jest,
co się właśnie stało, jakie wątki są otwarte>
""".strip()

_POLISH_INSTRUCTIONS = """
# Zadanie: redakcja stylistyczna

Dostajesz złożony z fragmentów draft podsumowania sesji RPG. Popraw wyłącznie
styl i płynność prozy: usuń powtórzenia na łączeniach fragmentów, wyrównaj ton,
popraw gramatykę i interpunkcję.

ZAKAZY (bezwzględne):
- NIE zmieniaj żadnych faktów, liczb, nazw własnych ani nazw zaklęć/przedmiotów.
- NIE zmieniaj kolejności wydarzeń ani sekcji.
- NIE dodawaj nowych wydarzeń, detali ani interpretacji.
- NIE usuwaj wydarzeń; możesz jedynie skracać rozwlekłe sformułowania.
- Zachowaj strukturę nagłówków `###` (możesz poprawić brzmienie nagłówka,
  nie jego sens).

Zwróć tylko poprawiony tekst podsumowania, bez komentarzy.
""".strip()


def _parse_chunk_response(text: str) -> tuple[str, str]:
    """Extract (narrative, rolling_summary) from a chunk response.

    Falls back to treating the whole response as narrative if the expected
    block markers are missing.
    """
    narrative_match = _NARRATIVE_RE.search(text)
    rolling_match = _ROLLING_RE.search(text)
    if narrative_match:
        narrative = narrative_match.group("body").strip()
    else:
        # Strip a trailing ROLLING_SUMMARY block if present, keep the rest.
        narrative = _ROLLING_RE.sub("", text).strip()
        log.warning("Chunk response missing NARRATIVE marker; using full text.")
    rolling = rolling_match.group("body").strip() if rolling_match else ""
    return narrative, rolling


def generate_summary_chunked(
    *,
    transcript_content: str,
    style_rules: str,
    anti_hallucination: str,
    glossary: str,
    model_name: str,
    context_dir: Path,
    temp_dir: Path,
    session_number: int,
    cache_file: Path,
    chunk_lines: int = 800,
    temperature: float = 0.3,
    polish_pass: bool = True,
    polish_temperature: float = 0.7,
    timeline_recent_sessions: int = 0,
) -> tuple[str, list[str]]:
    """Chunked map-reduce summary with a rolling context summary.

    The transcript is split into ~`chunk_lines`-line chunks at speaker-turn
    boundaries. Chunks are summarized sequentially; each call receives the
    rolling summary of everything before it. NARRATIVE blocks are concatenated
    strictly in order. Per-chunk results are cached in `temp_dir` so the
    pipeline stays resumable. Returns (summary, rolling_summaries).
    """
    rolling_summaries: list[str] = []
    if cache_file.exists():
        log.info("Existing chunked summary found at %s. Loading it…", cache_file)
        summary = cache_file.read_text(encoding="utf-8")
        for rolling_file in sorted(temp_dir.glob(f"summary_chunk_{session_number}_*.rolling.txt")):
            rolling_summaries.append(rolling_file.read_text(encoding="utf-8"))
        return summary, rolling_summaries

    system_prompt = "\n\n".join(
        part.strip()
        for part in (style_rules, anti_hallucination, glossary, _CHUNK_INSTRUCTIONS)
        if part.strip()
    )
    general_context = load_context_files(context_dir, timeline_recent_sessions)

    chunks = split_transcript(transcript_content, chunk_lines)
    model = genai.GenerativeModel(model_name=model_name, system_instruction=system_prompt)

    narratives: list[str] = []
    rolling = ""
    temp_dir.mkdir(parents=True, exist_ok=True)

    for index, chunk in enumerate(chunks, start=1):
        chunk_cache = temp_dir / f"summary_chunk_{session_number}_{index:03d}.txt"
        rolling_cache = temp_dir / f"summary_chunk_{session_number}_{index:03d}.rolling.txt"
        if chunk_cache.exists() and rolling_cache.exists():
            log.info("Chunk %d/%d already summarized. Loading cache.", index, len(chunks))
            narratives.append(chunk_cache.read_text(encoding="utf-8"))
            rolling = rolling_cache.read_text(encoding="utf-8")
            rolling_summaries.append(rolling)
            continue

        parts: list[str] = []
        if general_context and index == 1:
            parts.append(f"DODATKOWY KONTEKST KAMPANII:\n{general_context}\n\n---\n")
        if rolling:
            parts.append(f"ROLLING_SUMMARY (wydarzenia z wcześniejszych fragmentów):\n{rolling}\n\n---\n")
        parts.append(
            f"FRAGMENT TRANSKRYPCJI ({index}/{len(chunks)}):\n{chunk}"
        )

        log.info("Summarizing chunk %d/%d…", index, len(chunks))
        response = _call_with_retry(
            model.generate_content,
            [{"role": "user", "parts": ["\n".join(parts)]}],
            generation_config=genai.GenerationConfig(temperature=temperature),
        )
        narrative, rolling = _parse_chunk_response(response.text)
        narratives.append(narrative)
        rolling_summaries.append(rolling)
        chunk_cache.write_text(narrative, encoding="utf-8")
        rolling_cache.write_text(rolling, encoding="utf-8")
        log.info("Chunk %d/%d summarized and cached.", index, len(chunks))

    summary = "\n\n".join(n for n in narratives if n).strip()

    if polish_pass and summary:
        summary = _polish_summary(
            summary,
            model_name=model_name,
            style_rules=style_rules,
            anti_hallucination=anti_hallucination,
            temperature=polish_temperature,
        )

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(summary, encoding="utf-8")
    log.info("Chunked session summary saved to %s", cache_file)
    return summary, rolling_summaries


def _polish_summary(
    summary: str,
    *,
    model_name: str,
    style_rules: str,
    anti_hallucination: str,
    temperature: float,
) -> str:
    """One prose-polish pass. Instructed to change no facts, names, or order."""
    system_prompt = "\n\n".join(
        part.strip()
        for part in (style_rules, anti_hallucination, _POLISH_INSTRUCTIONS)
        if part.strip()
    )
    model = genai.GenerativeModel(model_name=model_name, system_instruction=system_prompt)
    log.info("Running final polish pass over the assembled summary…")
    try:
        response = _call_with_retry(
            model.generate_content,
            [{"role": "user", "parts": [f"DRAFT PODSUMOWANIA:\n{summary}"]}],
            generation_config=genai.GenerationConfig(temperature=temperature),
        )
        polished: str = response.text.strip()
    except Exception as e:
        log.warning("Polish pass failed (%s). Keeping the unpolished summary.", e)
        return summary
    if not polished:
        log.warning("Polish pass returned empty text. Keeping the unpolished summary.")
        return summary
    log.info("Polish pass complete.")
    return polished


def validate_summary(
    *,
    summary: str,
    transcript_content: str,
    validation_prompt: str,
    model_name: str,
    report_file: Path,
    max_iterations: int = 2,
) -> tuple[str, ValidationReport]:
    """Fact-check the draft against the transcript; auto-apply simple fixes.

    Runs up to `max_iterations` validate → fix rounds. Findings with
    severity="error" whose quote is found verbatim in the draft are applied as
    string replacements; everything else is left for the human in a Markdown
    report written to `report_file`. `transcript_content` is expected to be
    the enriched transcript, so `[CZAT]` chat-event lines (exact rolls, damage
    numbers and who cast what) and `[VISUAL]` anchors already sit inline as
    hard evidence. Returns (fixed_summary, last_report).
    """
    client = instructor.from_gemini(
        client=genai.GenerativeModel(
            model_name=model_name,
            system_instruction=validation_prompt,
        ),
        mode=instructor.Mode.GEMINI_JSON,
    )

    current = summary
    report = ValidationReport(findings=[])
    all_unapplied: list[Finding] = []

    evidence = f"TRANSKRYPCJA:\n{transcript_content}"

    for iteration in range(1, max_iterations + 1):
        log.info("Validation pass %d/%d…", iteration, max_iterations)
        report = _call_with_retry(
            client.chat.completions.create,
            messages=[
                {
                    "role": "user",
                    "content": f"DRAFT PODSUMOWANIA:\n{current}\n\n---\n\n{evidence}",
                }
            ],
            response_model=ValidationReport,
            max_retries=3,
        )
        if not report.findings:
            log.info("Validation pass %d found no issues.", iteration)
            break

        applied = 0
        unapplied: list[Finding] = []
        for finding in report.findings:
            if finding.severity == "error" and finding.quote and finding.quote in current:
                replacement = "" if finding.suggested_fix.strip().lower() == "remove" else finding.suggested_fix
                current = current.replace(finding.quote, replacement)
                applied += 1
            else:
                unapplied.append(finding)
        all_unapplied = unapplied
        log.info(
            "Validation pass %d: %d finding(s), %d auto-applied, %d left for review.",
            iteration,
            len(report.findings),
            applied,
            len(unapplied),
        )
        if applied == 0:
            break

    _write_validation_report(report_file, all_unapplied)
    return current, report


def _write_validation_report(report_file: Path, findings: list[Finding]) -> None:
    lines = ["# Raport walidacji podsumowania", ""]
    if not findings:
        lines.append("Brak nierozwiązanych uwag — wszystkie znalezione błędy naprawiono automatycznie.")
    else:
        lines.append("Poniższe uwagi wymagają ludzkiej weryfikacji:")
        lines.append("")
        for finding in findings:
            lines.append(f"## [{finding.severity}] {finding.issue}")
            lines.append("")
            lines.append(f"> {finding.quote}")
            if finding.suggested_fix:
                lines.append("")
                lines.append(f"**Sugerowana poprawka:** {finding.suggested_fix}")
            lines.append("")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    log.info("Validation report saved to %s", report_file)


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _quote_text(quote: str) -> str:
    """Extract the spoken part of a 'Speaker: "text"' quote line."""
    match = re.search(r'[":]\s*["„]?(?P<body>[^"”]+)', quote)
    return match.group("body") if match else quote


def verify_quotes(quotes: QuotesData, transcript_content: str) -> QuotesData:
    """Drop quotes that don't (fuzzily) appear in the transcript.

    A quote passes if its normalized spoken text is a substring of the
    normalized transcript, or if a long-enough prefix/suffix window matches
    (tolerates trailing paraphrase or elision).
    """
    normalized_transcript = _normalize_for_match(transcript_content)
    kept: list[str] = []
    for quote in quotes.quotes:
        body = _normalize_for_match(_quote_text(quote))
        if not body:
            log.warning("Dropping empty quote: %r", quote)
            continue
        candidates = [body]
        words = body.split()
        if len(words) > 6:
            candidates.append(" ".join(words[:6]))
            candidates.append(" ".join(words[-6:]))
        if any(candidate in normalized_transcript for candidate in candidates):
            kept.append(quote)
        else:
            log.warning("Dropping unverified quote (not found in transcript): %r", quote)
    log.info("Quote verification: %d/%d quotes kept.", len(kept), len(quotes.quotes))
    return QuotesData(quotes=kept)


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
