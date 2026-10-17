from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from ..hallucination import is_hallucination
from ..speakers import extract_speaker, load_mapping

log = logging.getLogger("rpgnotes")

# Whisper's own thresholds. avg_logprob / no_speech_prob / compression_ratio
# are per 30 s decode window (shared by all segments of the window), so a
# segment is dropped only when the window is BOTH likely silent and decoded
# with low confidence — Whisper's rule. Dropping on either condition alone
# discards whole windows of real but hard-to-decode speech, which is where
# rare fantasy names live.
_LOGPROB_THRESHOLD = -1.0
_NO_SPEECH_THRESHOLD = 0.6
# A window still above this after every temperature fallback is a repetition loop.
_COMPRESSION_RATIO_THRESHOLD = 2.4


def _drop_reason(segment: dict[str, Any], text: str) -> str | None:
    if not text or text in {"...", "..", "."}:
        return "empty"
    if (
        segment.get("no_speech_prob", 0.0) > _NO_SPEECH_THRESHOLD
        and segment.get("avg_logprob", 0.0) < _LOGPROB_THRESHOLD
    ):
        return "silence"
    if segment.get("compression_ratio", 0.0) > _COMPRESSION_RATIO_THRESHOLD:
        return "repetition"
    if is_hallucination(text):
        return "hallucination"
    return None


def combine_transcriptions(
    session_number: int,
    transcriptions_dir: Path,
    assets_base_dir: Path,
    mapping_file: Path,
) -> Path | None:
    """Merge per-speaker JSON transcripts into a single sorted JSON + TXT pair."""
    session_assets_dir = assets_base_dir / f"{session_number:03d}"
    session_assets_dir.mkdir(parents=True, exist_ok=True)
    combined_json_path = session_assets_dir / "transcript.json"
    combined_txt_path = session_assets_dir / "transcript.txt"

    if combined_json_path.exists() and combined_txt_path.exists():
        log.info(
            "Combined transcriptions for session %d already exist. Skipping.",
            session_number,
        )
        return combined_txt_path

    mapping = load_mapping(mapping_file)
    all_segments: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    dropped_words: Counter[str] = Counter()

    for json_file in sorted(transcriptions_dir.glob("*.json")):
        speaker = extract_speaker(json_file, mapping)
        with json_file.open(encoding="utf-8") as f:
            segments: list[dict[str, Any]] = json.load(f)

        for segment in segments:
            text = str(segment.get("text", "")).strip()
            reason = _drop_reason(segment, text)
            if reason is not None:
                dropped[reason] += 1
                dropped_words[reason] += len(text.split())
                continue
            if (
                all_segments
                and all_segments[-1]["speaker"] == speaker
                and str(all_segments[-1]["text"]).strip() == text
            ):
                continue

            segment["speaker"] = speaker
            all_segments.append(segment)

    all_segments.sort(key=lambda x: x["start"])
    if dropped:
        log.info(
            "Dropped segments: %s (kept %d segments, %d words).",
            ", ".join(
                f"{reason}={count} ({dropped_words[reason]} words)"
                for reason, count in dropped.most_common()
            ),
            len(all_segments),
            sum(len(str(seg["text"]).split()) for seg in all_segments),
        )

    combined_json_path.write_text(
        json.dumps(all_segments, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines: list[str] = []
    current_speaker: str | None = None
    for segment in all_segments:
        if segment["speaker"] != current_speaker:
            lines.append(f"\n\n[{segment['speaker']}]\n")
            current_speaker = segment["speaker"]
        lines.append(str(segment["text"]).strip() + " ")
    combined_txt_path.write_text("".join(lines), encoding="utf-8")

    log.info("Combined transcription saved to %s", combined_txt_path)
    return combined_txt_path
