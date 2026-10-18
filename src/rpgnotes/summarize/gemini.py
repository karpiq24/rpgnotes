from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from .. import llm
from .chunker import is_speaker_line, split_transcript
from .models import Finding, QuotesData, SessionData, ValidationReport

log = logging.getLogger("rpgnotes")


_NARRATIVE_RE = re.compile(
    r"NARRATIVE:?\s*\n(?P<body>.*?)(?=\n\s*ROLLING_SUMMARY|\Z)", re.DOTALL
)
_ROLLING_RE = re.compile(r"ROLLING_SUMMARY:?\s*\n(?P<body>.*)\Z", re.DOTALL)

_CHUNK_INSTRUCTIONS = """
# Zadanie: podsumowanie FRAGMENTU sesji

Dostajesz jeden fragment transkrypcji (sesja jest przetwarzana po kolei,
fragment po fragmencie) oraz ROLLING_SUMMARY — skrót tego, co wydarzyło się
we wcześniejszych fragmentach. Może pojawić się też KONIEC POPRZEDNIEGO
FRAGMENTU — ostatnie wypowiedzi, które są już opisane. Podsumuj TYLKO bieżący
fragment; ROLLING_SUMMARY i KONIEC POPRZEDNIEGO FRAGMENTU służą wyłącznie jako
kontekst (nie opisuj ponownie tych wydarzeń).

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
    temp_dir: Path,
    session_number: int,
    cache_file: Path,
    chunk_lines: int = 800,
    temperature: float | None = None,
    thinking_level: str | None = None,
    polish_pass: bool = True,
    polish_temperature: float | None = None,
    campaign_rules: str = "",
    background: str = "",
    overlap_lines: int = 40,
) -> tuple[str, list[str]]:
    """Chunked map-reduce summary with a rolling context summary.

    The transcript is split into ~`chunk_lines`-line chunks at speaker-turn
    boundaries. Chunks are summarized sequentially; each call receives the
    rolling summary of everything before it. NARRATIVE blocks are concatenated
    strictly in order. Per-chunk results are cached in `temp_dir` so the
    pipeline stays resumable. The campaign rules (party, learned rules) and
    the `background` (campaign summary + recent timeline) sit in the system prompt
    so every chunk (not just the first) can identify NPCs and places, and each
    chunk also sees the last `overlap_lines` lines of the previous chunk so
    events straddling a boundary keep their context. Returns
    (summary, rolling_summaries).
    """
    rolling_summaries: list[str] = []
    if cache_file.exists():
        log.info("Existing chunked summary found at %s. Loading it…", cache_file)
        summary = cache_file.read_text(encoding="utf-8")
        for rolling_file in sorted(temp_dir.glob(f"summary_chunk_{session_number}_*.rolling.txt")):
            rolling_summaries.append(rolling_file.read_text(encoding="utf-8"))
        return summary, rolling_summaries

    context_block = (
        f"# Kontekst kampanii (tło — nie opisuj go jako wydarzeń tej sesji)\n\n{background}"
        if background.strip()
        else ""
    )
    system_prompt = "\n\n".join(
        part.strip()
        for part in (
            style_rules,
            anti_hallucination,
            campaign_rules,
            glossary,
            context_block,
            _CHUNK_INSTRUCTIONS,
        )
        if part.strip()
    )

    chunks = split_transcript(transcript_content, chunk_lines)

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
        if index > 1 and overlap_lines > 0:
            tail = "\n".join(chunks[index - 2].splitlines()[-overlap_lines:]).strip()
            parts.append(
                "KONIEC POPRZEDNIEGO FRAGMENTU (już opisany — tylko kontekst):\n"
                f"{tail}\n\n---\n"
            )
        if rolling:
            parts.append(f"ROLLING_SUMMARY (wydarzenia z wcześniejszych fragmentów):\n{rolling}\n\n---\n")
        parts.append(
            f"FRAGMENT TRANSKRYPCJI ({index}/{len(chunks)}):\n{chunk}"
        )

        log.info("Summarizing chunk %d/%d…", index, len(chunks))
        response_text = llm.generate_text(
            model=model_name,
            contents="\n".join(parts),
            system_instruction=system_prompt,
            temperature=temperature,
            thinking_level=thinking_level,
        )
        narrative, rolling = _parse_chunk_response(response_text)
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
            campaign_rules=campaign_rules,
            temperature=polish_temperature,
            thinking_level=thinking_level,
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
    temperature: float | None,
    campaign_rules: str = "",
    thinking_level: str | None = None,
) -> str:
    """One prose-polish pass. Instructed to change no facts, names, or order."""
    system_prompt = "\n\n".join(
        part.strip()
        for part in (style_rules, anti_hallucination, campaign_rules, _POLISH_INSTRUCTIONS)
        if part.strip()
    )
    log.info("Running final polish pass over the assembled summary…")
    try:
        polished = llm.generate_text(
            model=model_name,
            contents=f"DRAFT PODSUMOWANIA:\n{summary}",
            system_instruction=system_prompt,
            temperature=temperature,
            thinking_level=thinking_level,
        ).strip()
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
    glossary: str = "",
    campaign_rules: str = "",
    thinking_level: str | None = None,
    max_iterations: int = 2,
) -> tuple[str, ValidationReport]:
    """Fact-check the draft against the transcript; auto-apply simple fixes.

    Runs up to `max_iterations` validate → fix rounds. Findings with
    severity="error" whose quote occurs exactly once in the draft are applied
    as string replacements; everything else is left for the human in a JSON
    `ValidationReport` written to `report_file`. The session `glossary` and the
    `campaign_rules` go into the system prompt so the checker knows canonical
    names are correct even when the transcript spells them the way the ASR
    heard them.
    `transcript_content` is expected to be
    the enriched transcript, so `[CZAT]` chat-event lines (exact rolls, damage
    numbers and who cast what) and `[VISUAL]` anchors already sit inline as
    hard evidence. Returns (fixed_summary, last_report).
    """
    system_prompt = "\n\n".join(
        part.strip() for part in (validation_prompt, campaign_rules, glossary) if part.strip()
    )
    current = summary
    report = ValidationReport(findings=[])
    all_unapplied: list[Finding] = []

    evidence = f"TRANSKRYPCJA:\n{transcript_content}"

    for iteration in range(1, max_iterations + 1):
        log.info("Validation pass %d/%d…", iteration, max_iterations)
        report = llm.generate_structured(
            model=model_name,
            contents=f"DRAFT PODSUMOWANIA:\n{current}\n\n---\n\n{evidence}",
            schema=ValidationReport,
            system_instruction=system_prompt,
            thinking_level=thinking_level,
        )
        if not report.findings:
            log.info("Validation pass %d found no issues.", iteration)
            break

        applied = 0
        unapplied: list[Finding] = []
        for finding in report.findings:
            # Only unambiguous quotes: a short quote like a bare name can occur
            # many times, and replacing every occurrence rewrites correct text.
            if finding.severity == "error" and finding.quote and current.count(finding.quote) == 1:
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
    """The findings left for a human, as a `ValidationReport` JSON file."""
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        ValidationReport(findings=findings).model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    log.info("Validation report with %d open finding(s) saved to %s", len(findings), report_file)


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


def _speaker_texts(transcript_content: str) -> dict[str, str]:
    """Normalized spoken text per speaker, from the `[Speaker]`-header transcript."""
    texts: dict[str, list[str]] = {}
    current: str | None = None
    for line in transcript_content.splitlines():
        if is_speaker_line(line):
            current = line.strip()[1:-1].strip()
        elif current is not None and line.strip():
            texts.setdefault(current, []).append(_normalize_for_match(line))
    return {speaker: " | ".join(parts) for speaker, parts in texts.items()}


def _resolve_speaker(claimed: str, speakers: list[str]) -> str | None:
    """Map a quote's speaker label ("Arevon Elorrenthi") to a transcript header ("Arevon")."""
    claimed_norm = _normalize_for_match(claimed)
    if not claimed_norm:
        return None
    for speaker in speakers:
        speaker_norm = _normalize_for_match(speaker)
        if speaker_norm and (
            claimed_norm == speaker_norm
            or claimed_norm.split()[0] == speaker_norm.split()[0]
        ):
            return speaker
    return None


def verify_quotes(quotes: QuotesData, transcript_content: str) -> QuotesData:
    """Drop quotes that don't (fuzzily) appear in the transcript; fix misattributions.

    A quote passes if its normalized spoken text is a substring of the
    normalized transcript, or if a long-enough prefix/suffix window matches
    (tolerates trailing paraphrase or elision). When the quote's speaker is a
    known transcript speaker who never said it, but exactly one other speaker
    did, the attribution is rewritten to that speaker.
    """
    normalized_transcript = _normalize_for_match(transcript_content)
    by_speaker = _speaker_texts(transcript_content)
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
        if not any(candidate in normalized_transcript for candidate in candidates):
            log.warning("Dropping unverified quote (not found in transcript): %r", quote)
            continue

        claimed, sep, rest = quote.partition(":")
        claimed_speaker = _resolve_speaker(claimed, list(by_speaker)) if sep else None
        if claimed_speaker is not None:
            said_by = [
                speaker
                for speaker, text in by_speaker.items()
                if any(candidate in text for candidate in candidates)
            ]
            if claimed_speaker not in said_by and len(said_by) == 1:
                log.warning(
                    "Quote attributed to %s but spoken by %s; fixing: %r",
                    claimed.strip(),
                    said_by[0],
                    quote,
                )
                quote = f"{said_by[0]}:{rest}"
        kept.append(quote)
    log.info("Quote verification: %d/%d quotes kept.", len(kept), len(quotes.quotes))
    return QuotesData(quotes=kept)


def generate_quotes(
    *,
    transcript_content: str,
    quotes_prompt: str,
    model_name: str,
    cache_file: Path,
    campaign_rules: str = "",
) -> QuotesData:
    """Extract memorable quotes from the transcript. Reads from `cache_file` if present."""
    if cache_file.exists():
        log.info("Existing quotes found at %s. Loading it…", cache_file)
        try:
            return QuotesData.model_validate_json(cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to load existing quotes from %s: %s. Re-generating.", cache_file, e)

    log.info("Extracting memorable quotes…")
    data = llm.generate_structured(
        model=model_name,
        contents=f"PEŁNA TRANSKRYPCJA:\n{transcript_content}",
        schema=QuotesData,
        system_instruction="\n\n".join(
            part.strip() for part in (quotes_prompt, campaign_rules) if part.strip()
        ),
    )
    log.info("Quotes extracted.")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    log.info("Interim quotes saved to %s", cache_file)
    return data


def generate_details(
    *,
    summary: str,
    details_prompt: str,
    model_name: str,
    cache_file: Path,
    campaign_rules: str = "",
    glossary: str = "",
) -> SessionData:
    """Title, key events, NPCs, locations and items, derived from the final draft.

    Reads from `cache_file` if present.
    """
    if cache_file.exists():
        log.info("Existing session details found at %s. Loading them…", cache_file)
        try:
            return SessionData.model_validate_json(cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to load session details from %s: %s. Re-generating.", cache_file, e)

    log.info("Generating session details (title, events, NPCs, locations, items)…")
    data = llm.generate_structured(
        model=model_name,
        contents=f"PODSUMOWANIE SESJI:\n{summary}",
        schema=SessionData,
        system_instruction="\n\n".join(
            part.strip() for part in (details_prompt, campaign_rules, glossary) if part.strip()
        ),
    )
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    log.info("Session details saved to %s", cache_file)
    return data
