# Screen capture (without the Foundry module)

With the Foundry recorder module this section is not needed: its map snapshots are used instead. The screen capture script below still works without the module.

Capture the VTT screen during the session and the pipeline will interleave Gemini-captioned `[VISUAL HH:MM:SS] …` anchor lines into the transcript — hard evidence of scene changes, token positions, and handouts for the summarizer and fact-checker.

**Before the session starts** (alongside starting Craig), run on the host:

```bash
./run.sh capture        # = python3 scripts/capture_session.py
```

Pick the monitor showing the VTT (never the one with Discord — only the selected region is ever written to disk), leave it running, stop with `Ctrl+C` after the session.

To skip the picker, set `CAPTURE_MONITOR` (connector name like `DP-1`, or an EDID model substring like `LG`, so it survives moving cables) and optionally `CAPTURE_CROP=WxH+X+Y` in `.env` — a sub-region in that monitor's own pixels, e.g. only the Foundry page inside a maximized Firefox, without desktop panels, browser toolbars, bookmarks or the vertical-tabs column. Then a bare `./run.sh capture` needs no input. Measure the crop once from a `--once` test frame, and re-measure if the panel or browser layout changes (Firefox fullscreen/F11 hides the toolbars, so the crop would then cut into Foundry). Frames land in `SCREENSHOTS_DIR` (default `TEMP_DIR/screenshots`, i.e. `./temp/screenshots/`) as `shot_<unix_ts>.png` plus a `session_start.txt` timestamp; frames nearly identical to the previous kept one are dropped automatically. Restarting within 12 h resumes the same capture; a capture started later moves the old frames to `previous/` (one game kept as backup; `--fresh` forces this). At ingestion, frames taken over an hour before the Craig recording started are skipped as leftovers.

Flags: `--interval N` (seconds between capture attempts, default 600 — D&D scenes change slowly and each kept frame costs a Gemini caption call, so 10 minutes is plenty; near-identical frames are still dropped immediately), `--monitor DP-1` / `--region WxH+X+Y` (skip the interactive picker), `--output-dir PATH`, `--dedupe-threshold F` (mean 0-255 gray diff, default 4.0), `--once` (single test frame).

Backends are auto-detected: `grim`+`slurp` (wlroots Wayland), Spectacle (KDE Plasma, e.g. Fedora KDE — needs `spectacle` + ImageMagick, both preinstalled or `sudo dnf install spectacle ImageMagick`; no permission prompt, monitors listed via `kscreen-doctor`, works with mixed display scaling), the XDG desktop portal (GNOME Wayland; needs ImageMagick + `python3-dbus`/`python3-gi`), or `maim`/`scrot`/ImageMagick (X11). On GNOME Wayland, run this once so the portal stops asking for permission:

```bash
python3 scripts/capture_session.py --grant-portal-permission
```

(The GNOME portal and Spectacle briefly write a full-desktop frame — GNOME to your Pictures dir, Spectacle to a private temp dir; the script crops it to your region and deletes the original immediately. GNOME may flash the screen on each capture — that's normal.)

**Ingestion** is enabled by setting `SCREENSHOTS_DIR` in `.env` (e.g. `./temp/screenshots`, where the capture script writes by default; clearing the temp dir at startup keeps this folder); leave it empty and the pipeline behaves exactly as before. Each kept frame gets one Gemini Flash multimodal caption (Polish, glossary-anchored; model via `VISUAL_CAPTION_MODEL`, defaults to `GEMINI_FLASH_MODEL`; per-frame captions cached in `TEMP_DIR`, resumable). Outputs land in the session's outbox folder `OUTPUT_DIR/<NNN>/`: `visual_log.json` (`[{offset_secs, caption, path, is_key}]` — files named `shot_<ts>_key.png` are flagged as key moments); the captions are merged into `transcript_enriched.txt` (see the enriched transcript section of the README), which is fed to the summarizer. `VISUAL_DEDUPE=false` disables the ingestion-side re-dedupe.

Offsets are anchored to Craig's recording start (`recording_start.txt`, parsed from the audio zip's `info.txt`) when available — this survives starting the capture script earlier or later than the recording. `session_start.txt` is only the fallback anchor. `VISUAL_CROP=WxH+X+Y` cuts system/browser chrome (dock, tabs, clock) out of both the AI upload and the dedupe signature; disk originals are never modified.
