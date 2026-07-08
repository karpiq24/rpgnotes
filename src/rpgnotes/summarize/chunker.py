from __future__ import annotations

import logging
import re

log = logging.getLogger("rpgnotes")

# A speaker-turn header in the combined transcript looks like a line that is
# nothing but "[Some Speaker]" (see transcribe/combine.py).
_SPEAKER_LINE = re.compile(r"^\s*\[[^\]]+\]\s*$")


def is_speaker_line(line: str) -> bool:
    """True if `line` is a speaker-turn header (e.g. "[Orestes]")."""
    return bool(_SPEAKER_LINE.match(line))


def split_transcript(transcript: str, chunk_lines: int = 800) -> list[str]:
    """Split a combined transcript into ~`chunk_lines`-line chunks.

    Cuts are only ever made *before* a speaker-turn header, so a chunk always
    ends at a speaker-turn boundary and no speaker's turn is torn in half. A
    single turn longer than `chunk_lines` stays whole (it becomes an oversized
    chunk rather than being split mid-turn).
    """
    if chunk_lines <= 0:
        raise ValueError("chunk_lines must be a positive integer")

    lines = transcript.splitlines()
    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        # Start a new chunk only at a speaker boundary, and only once the
        # current chunk already has content worth keeping.
        if is_speaker_line(line) and len(current) >= chunk_lines:
            chunks.append("\n".join(current).strip())
            current = []
        current.append(line)

    tail = "\n".join(current).strip()
    if tail:
        chunks.append(tail)

    chunks = [c for c in chunks if c.strip()]
    log.info("Split transcript (%d lines) into %d chunk(s).", len(lines), len(chunks))
    return chunks
