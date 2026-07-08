from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import google.generativeai as genai
from pydantic import BaseModel

from .summarize.gemini import _call_with_retry

log = logging.getLogger("rpgnotes")

SIGNATURE_SIZE = 64  # downscale side used for dedupe signatures

_SHOT_RE = re.compile(r"^shot_(\d+)(_key)?\.png$")


class VisualEntry(BaseModel):
    """One captioned session screenshot, positioned on the recording timeline."""

    offset_secs: float
    caption: str
    path: str
    is_key: bool = False


def parse_screenshot_timestamp(path: Path) -> tuple[int, bool] | None:
    """Extract (unix_ts, is_key) from a `shot_<ts>.png` / `shot_<ts>_key.png` name."""
    match = _SHOT_RE.match(path.name)
    if not match:
        return None
    return int(match.group(1)), match.group(2) is not None


def load_session_start(screenshots_dir: Path) -> int | None:
    """Read the unix start timestamp written by the capture script, if present."""
    start_file = screenshots_dir / "session_start.txt"
    if not start_file.exists():
        return None
    try:
        return int(start_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as e:
        log.warning("Could not read %s: %s", start_file, e)
        return None


# --------------------------------------------------------------------------
# Dedupe
# --------------------------------------------------------------------------


def mean_abs_diff(a: bytes, b: bytes) -> float:
    """Mean absolute per-pixel difference of two equal-length gray buffers (0-255).

    Mismatched or empty buffers compare as maximally different.
    """
    if len(a) != len(b) or not a:
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


def frame_signature(path: Path, crop: str = "") -> bytes | None:
    """64x64 grayscale raw bytes of the frame via ImageMagick, or None if unavailable.

    When `crop` (ImageMagick geometry, e.g. "2496x1335+64+105") is set, the
    signature covers only that region — system chrome (clock, browser tabs)
    then never influences dedupe decisions.
    """
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        return None
    crop_args = ["-crop", crop, "+repage"] if crop else []
    try:
        proc = subprocess.run(
            [
                magick,
                str(path),
                *crop_args,
                "-resize",
                f"{SIGNATURE_SIZE}x{SIGNATURE_SIZE}!",
                "-colorspace",
                "Gray",
                "-depth",
                "8",
                "GRAY:-",
            ],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    expected = SIGNATURE_SIZE * SIGNATURE_SIZE
    if proc.returncode != 0 or len(proc.stdout) != expected:
        return None
    return proc.stdout


def _dedupe_frames(
    shots: list[tuple[Path, int, bool]], threshold: float, crop: str = ""
) -> list[tuple[Path, int, bool]]:
    """Drop frames nearly identical to the previous KEPT frame. Key frames always stay."""
    kept: list[tuple[Path, int, bool]] = []
    prev_signature: bytes | None = None
    dropped = 0
    for shot in shots:
        path, _ts, is_key = shot
        signature = frame_signature(path, crop)
        if signature is None:
            log.warning("No dedupe signature for %s (ImageMagick missing?). Keeping frame.", path)
            kept.append(shot)
            prev_signature = None
            continue
        if (
            not is_key
            and prev_signature is not None
            and mean_abs_diff(signature, prev_signature) < threshold
        ):
            dropped += 1
            continue
        kept.append(shot)
        prev_signature = signature
    log.info("Screenshot dedupe: %d kept, %d dropped.", len(kept), dropped)
    return kept


# --------------------------------------------------------------------------
# Upload preparation
# --------------------------------------------------------------------------


def prepare_upload(
    path: Path, *, max_dim: int = 1536, jpeg_quality: int = 80, crop: str = ""
) -> tuple[bytes, str]:
    """Return (image_bytes, mime_type) for the caption API call.

    Full-resolution PNGs stay on disk untouched; for the upload the frame is
    optionally cropped to the `crop` geometry (cuts system/browser chrome),
    downscaled to at most `max_dim` on its long edge and re-encoded as JPEG —
    the caption model tiles images at far lower resolution than a VTT
    screenshot, so this loses nothing while shrinking the payload ~10-20x.
    Falls back to the original PNG bytes when compression is disabled
    (`max_dim` 0 with no crop) or ImageMagick is unavailable/fails.
    """
    if max_dim <= 0 and not crop:
        return path.read_bytes(), "image/png"
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        log.warning("ImageMagick not found — uploading %s uncompressed.", path.name)
        return path.read_bytes(), "image/png"
    crop_args = ["-crop", crop, "+repage"] if crop else []
    resize_args = ["-resize", f"{max_dim}x{max_dim}>"] if max_dim > 0 else []
    try:
        proc = subprocess.run(
            [
                magick,
                str(path),
                *crop_args,
                *resize_args,  # only shrinks, never enlarges
                "-strip",
                "-quality",
                str(jpeg_quality),
                "jpeg:-",
            ],
            capture_output=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("Compression failed for %s (%s) — uploading uncompressed.", path.name, e)
        return path.read_bytes(), "image/png"
    if proc.returncode != 0 or not proc.stdout:
        log.warning(
            "Compression failed for %s (%s) — uploading uncompressed.",
            path.name,
            proc.stderr.decode(errors="replace").strip() or "empty output",
        )
        return path.read_bytes(), "image/png"
    return proc.stdout, "image/jpeg"


# --------------------------------------------------------------------------
# Captioning
# --------------------------------------------------------------------------


def caption_screenshots(
    *,
    screenshots_dir: Path,
    caption_prompt: str,
    glossary: str,
    model_name: str,
    temp_dir: Path,
    session_number: int,
    visual_log_file: Path,
    dedupe: bool = True,
    dedupe_threshold: float = 4.0,
    api_sleep_secs: float = 0.0,
    upload_max_dim: int = 1536,
    upload_jpeg_quality: int = 80,
    crop: str = "",
    recording_start: int | None = None,
) -> list[VisualEntry]:
    """Caption session screenshots with Gemini Flash into a `visual_log.json`.

    Screenshot wall-clock timestamps (from `shot_<unix_ts>.png` filenames) are
    mapped to recording offsets via `recording_start` (the Craig audio start —
    the authoritative anchor shared with the transcript and chat log) when
    given, else `session_start.txt`, else the earliest screenshot as t=0.
    Per-frame captions are cached in `temp_dir` and the assembled log in
    `visual_log_file`, so the step is resumable like the other pipeline steps.
    """
    if visual_log_file.exists():
        log.info("Existing visual log found at %s. Loading it…", visual_log_file)
        try:
            raw = json.loads(visual_log_file.read_text(encoding="utf-8"))
            return [VisualEntry.model_validate(item) for item in raw]
        except Exception as e:
            log.warning("Failed to load %s: %s. Re-captioning.", visual_log_file, e)

    shots: list[tuple[Path, int, bool]] = []
    for path in screenshots_dir.glob("shot_*.png"):
        parsed = parse_screenshot_timestamp(path)
        if parsed is None:
            log.warning("Skipping screenshot with unrecognized name: %s", path.name)
            continue
        shots.append((path, parsed[0], parsed[1]))
    shots.sort(key=lambda shot: shot[1])
    if not shots:
        log.info("No screenshots found in %s.", screenshots_dir)
        return []

    if recording_start is not None:
        session_start = recording_start
        log.info("Using Craig recording start (%d) as the visual offset anchor.", session_start)
    else:
        loaded_start = load_session_start(screenshots_dir)
        if loaded_start is None:
            loaded_start = shots[0][1]
            log.warning(
                "session_start.txt missing in %s — using earliest screenshot (%d) as t=0. "
                "Offsets may drift from the audio recording start.",
                screenshots_dir,
                loaded_start,
            )
        session_start = loaded_start

    if dedupe:
        shots = _dedupe_frames(shots, dedupe_threshold, crop)

    system_prompt = "\n\n".join(part.strip() for part in (caption_prompt, glossary) if part.strip())
    model = genai.GenerativeModel(model_name=model_name, system_instruction=system_prompt)

    entries: list[VisualEntry] = []
    made_api_call = False
    for path, ts, is_key in shots:
        offset = float(ts - session_start)
        if offset < 0:
            log.warning("Screenshot %s predates session start. Clamping offset to 0.", path.name)
            offset = 0.0

        cache_file = temp_dir / f"visual_caption_{session_number}_{ts}.txt"
        if cache_file.exists():
            caption = cache_file.read_text(encoding="utf-8").strip()
        else:
            if made_api_call and api_sleep_secs > 0:
                time.sleep(api_sleep_secs)
            log.info("Captioning %s (offset %s)…", path.name, format_offset(offset))
            data, mime_type = prepare_upload(
                path, max_dim=upload_max_dim, jpeg_quality=upload_jpeg_quality, crop=crop
            )
            try:
                response = _call_with_retry(
                    model.generate_content,
                    [
                        {"mime_type": mime_type, "data": data},
                        "Opisz ten zrzut ekranu z sesji zgodnie z instrukcją.",
                    ],
                )
                made_api_call = True
                caption = str(response.text).strip()
            except Exception as e:
                log.warning("Captioning failed for %s: %s. Skipping frame.", path.name, e)
                continue
            temp_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(caption, encoding="utf-8")

        if not caption:
            log.warning("Empty caption for %s. Skipping frame.", path.name)
            continue
        entries.append(
            VisualEntry(offset_secs=offset, caption=caption, path=str(path), is_key=is_key)
        )

    visual_log_file.parent.mkdir(parents=True, exist_ok=True)
    visual_log_file.write_text(
        json.dumps([entry.model_dump() for entry in entries], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Visual log with %d caption(s) saved to %s", len(entries), visual_log_file)
    return entries


# --------------------------------------------------------------------------
# Transcript interleaving
# --------------------------------------------------------------------------


def format_offset(offset_secs: float) -> str:
    """Format a recording offset as HH:MM:SS."""
    total = max(0, int(offset_secs))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def interleave_visuals(segments: list[dict[str, Any]], entries: list[VisualEntry]) -> str:
    """Render transcript segments with `[VISUAL HH:MM:SS] …` lines interleaved.

    Thin wrapper over `enrich.build_enriched_transcript` with no chat events;
    see that function for the merge semantics.
    """
    from .enrich import build_enriched_transcript  # local import: enrich imports this module

    return build_enriched_transcript(segments, entries, [])
