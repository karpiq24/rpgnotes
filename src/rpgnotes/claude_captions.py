"""Caption the map snapshots in a Claude Code session instead of calling Gemini.

`export_caption_tasks` puts the frames still missing a caption into
`TEMP_DIR/claude_captions/` (downscaled JPEGs, `tasks.json`, `instructions.md`);
the `/caption-frames` skill has Claude subagents write one caption file per
frame into its `captions/` folder; `import_captions` checks them and stores
them where the pipeline keeps captions (`visual.caption_cache_file`), so the
next run uses them without any caption API call.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from .campaign import load_campaign_context
from .config import Settings
from .summarize import build_session_glossary
from .visual import (
    caption_cache_file,
    format_offset,
    frame_hint,
    load_frame_info,
    prepare_upload,
    select_frames,
)

log = logging.getLogger("rpgnotes")

TASKS_FILE = "tasks.json"
INSTRUCTIONS_FILE = "instructions.md"
# A caption is 2-4 sentences; anything far longer is the agent's commentary.
MAX_CAPTION_CHARS = 1200

_OUTPUT_RULES = """
## Format odpowiedzi

Dla każdej klatki zapisz plik tekstowy UTF-8 pod ścieżką podaną w `caption`
(względem tego folderu), zawierający WYŁĄCZNIE opis: 2-4 zdania po polsku,
bez nagłówków, list, cudzysłowów ani komentarzy o zadaniu. Linia `hint` przy
klatce to fakty zapisane przez Foundry (nazwa sceny, tytuł handoutu): użyj
ich, ale opisuj to, co widać.
"""


def export_caption_tasks(
    settings: Settings,
    session_number: int,
    screenshots_dir: Path,
    crop: str,
    recording_start: int | None,
) -> int:
    """Write the frames without a caption and their task list. Returns how many."""
    out = settings.claude_captions_dir
    tasks_file = out / TASKS_FILE
    previous = _read_tasks(tasks_file)
    if previous is not None and previous.get("session") != session_number:
        shutil.rmtree(out)  # another session's frames and captions
    frames_dir, captions_dir = out / "frames", out / "captions"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    captions_dir.mkdir(parents=True, exist_ok=True)

    frames = select_frames(
        screenshots_dir,
        dedupe=settings.visual_dedupe,
        crop=crop,
        recording_start=recording_start,
    )
    info = load_frame_info(screenshots_dir)
    tasks = []
    for frame in frames:
        if caption_cache_file(settings.temp_dir, session_number, frame.ts).exists():
            continue
        data, mime = prepare_upload(
            frame.path,
            max_dim=settings.visual_upload_max_dim,
            jpeg_quality=settings.visual_upload_jpeg_quality,
            crop=crop,
        )
        image = frames_dir / f"{frame.ts}{'.jpg' if mime == 'image/jpeg' else frame.path.suffix}"
        image.write_bytes(data)
        tasks.append(
            {
                "id": str(frame.ts),
                "image": str(image.relative_to(out)),
                "caption": f"captions/{frame.ts}.txt",
                "offset": format_offset(frame.offset),
                "key": frame.is_key,
                "hint": frame_hint(info.get(frame.path.name, {})).strip(),
            }
        )

    context = load_campaign_context(settings.campaign_context_file)
    glossary = build_session_glossary(context, include_aliases=False, include_phonetic=False)
    prompt = settings.visual_caption_prompt_file.read_text(encoding="utf-8").strip()
    (out / INSTRUCTIONS_FILE).write_text(
        "\n\n".join(part for part in (prompt, glossary.strip(), _OUTPUT_RULES.strip()) if part)
        + "\n",
        encoding="utf-8",
    )
    tasks_file.write_text(
        json.dumps({"session": session_number, "frames": tasks}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info(
        "%d frame(s) to caption written to %s (%d already captioned).",
        len(tasks),
        out,
        len(frames) - len(tasks),
    )
    return len(tasks)


def import_captions(settings: Settings, session_number: int) -> tuple[int, int]:
    """Store the captions written in Claude Code. Returns (imported, still missing)."""
    out = settings.claude_captions_dir
    tasks = _read_tasks(out / TASKS_FILE)
    if tasks is None or tasks.get("session") != session_number:
        log.error("No caption tasks for session %d. Run captions-export first.", session_number)
        return 0, 0
    imported = missing = 0
    for task in tasks.get("frames", []):
        try:
            caption = (out / task["caption"]).read_text(encoding="utf-8").strip()
        except (OSError, KeyError):
            caption = ""
        if not caption or len(caption) > MAX_CAPTION_CHARS:
            if caption:
                log.warning("Caption for frame %s is %d characters long; skipped.",
                            task.get("id"), len(caption))
            missing += 1
            continue
        cache = caption_cache_file(settings.temp_dir, session_number, int(task["id"]))
        cache.write_text(caption + "\n", encoding="utf-8")
        imported += 1
    if imported:
        # Built from the previous caption set: rebuilt on the next run.
        session_dir = settings.session_dir(session_number)
        for stale in ("visual_log.json", "transcript_enriched.txt"):
            (session_dir / stale).unlink(missing_ok=True)
    log.info("Imported %d caption(s); %d frame(s) still without one.", imported, missing)
    return imported, missing


def pending_captions(settings: Settings, session_number: int) -> int | None:
    """Exported frames without an imported caption, or None when nothing was exported."""
    tasks = _read_tasks(settings.claude_captions_dir / TASKS_FILE)
    if tasks is None or tasks.get("session") != session_number:
        return None
    return sum(
        not caption_cache_file(settings.temp_dir, session_number, int(task["id"])).exists()
        for task in tasks.get("frames", [])
    )


def _read_tasks(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
