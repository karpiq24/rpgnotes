from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..hallucination import is_hallucination
from ..speakers import extract_speaker, load_mapping

log = logging.getLogger("rpgnotes")


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

    for json_file in sorted(transcriptions_dir.glob("*.json")):
        speaker = extract_speaker(json_file, mapping)
        with json_file.open(encoding="utf-8") as f:
            segments: list[dict[str, Any]] = json.load(f)

        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if segment.get("avg_logprob", 0.0) < -1.0:
                continue
            if segment.get("no_speech_prob", 0.0) > 0.6:
                continue
            if not text or text in {"...", "..", "."}:
                continue
            if is_hallucination(text):
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
