# RPG Session Notes Automator

Turn a TTRPG session bundle — a `craig-*.flac.zip` of per-speaker audio plus a `session*.json` chat log — into a validated, AI-drafted session recap (`draft0.md`), which OotD assembles into the final session note after the refine pass.

- **Transcription**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on CTranslate2 — AMD ROCm and NVIDIA CUDA both work.
- **Summarization**: Google Gemini (via `google-generativeai` + `instructor` for structured output).
- **Run**: a single `./run.sh` after dropping files into `DOWNLOADS_DIR`.

## Quick start

```bash
cp .env.example .env
$EDITOR .env                    # set GEMINI_API_KEY at minimum
docker compose build
./run.sh                        # processes the newest session in DOWNLOADS_DIR
```

That's it. Per-session artifacts (including `draft0.md`) end up in `OUTPUT_DIR/assets/sessions/<NNN>/` — point `OUTPUT_DIR` at an OotD checkout's `content/` directory and they're immediately visible there, no copy step needed. The final `Sesja XX - <title>.md` note is rendered by OotD after refinement (the manual workflow still renders it locally into `OUTPUT_DIR/01-Sessions/`).

## Commands

| Command | What it does |
|---|---|
| `./run.sh` | Full workflow: transcribe + Gemini summary/quotes for the newest session. |
| `./run.sh transcribe` | Transcription only (no Gemini calls). |
| `./run.sh manual` | Skip Gemini; paste summary/details/quotes JSON manually (renders the final note locally). |
| `./run.sh --menu` | Legacy interactive menu (same as old `main.py`). |
| `./run.sh --clean-temp` | Wipe `TEMP_DIR` first. |

## Day-to-day workflow

1. After the session, drop two files into `DOWNLOADS_DIR`:
   - `craig-*.flac.zip` — Craig bot audio archive
   - `session<NN>.json` — your chat log (the script extracts the session number and date from this file)
2. Run `./run.sh`. The pipeline is resumable: re-running skips steps that already produced output.

## AMD GPU support

The Docker image is based on `rocm/dev-ubuntu-24.04:7.2.2-complete` and ships the official CTranslate2 v4.7.1 ROCm wheel. Tested on an AMD Radeon RX 9070 XT (gfx1201, RDNA4). Other supported targets per the [CT2 v4.7.1 release](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.7.1): gfx803, gfx900, gfx906, gfx908, gfx90a, gfx942, gfx950, gfx1030, gfx1100, gfx1101, gfx1102, gfx1150, gfx1151, gfx1200, gfx1201.

The container uses `device="cuda"` even on ROCm — CTranslate2 keeps that name. Override via `WHISPER_DEVICE=cpu` (and `WHISPER_COMPUTE_TYPE=int8`) if you need to.

Required device passthrough is already wired into `docker-compose.yml`: `/dev/kfd`, `/dev/dri`, `group_add: video,render`. Ensure your host user is in those groups.

## NVIDIA GPU support

Replace the base image in [docker/Dockerfile](docker/Dockerfile) with a CUDA-equipped one (e.g. `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu24.04`), drop the CT2 ROCm wheel step (use `pip install ctranslate2` for the standard CUDA build), and replace the `devices`/`group_add` block in `docker-compose.yml` with `runtime: nvidia` plus the standard NVIDIA Container Toolkit setup.

## Running without Docker

If you'd rather run on the host:

```bash
python -m venv .venv && source .venv/bin/activate
# AMD: install the CT2 ROCm wheel from https://github.com/OpenNMT/CTranslate2/releases/tag/v4.7.1
# NVIDIA: pip install ctranslate2
pip install -e ".[dev]"
python -m rpgnotes
```

## Configuration

All knobs live in `.env`. See [.env.example](.env.example) for the full list.

Key summarization knobs (chunked map-reduce summarizer):

- `SUMMARY_CHUNK_LINES` — transcript chunk size in lines (default `800`); chunks break only at speaker-turn boundaries.
- `SUMMARY_TEMPERATURE` — temperature for the factual per-chunk summaries (default `0.3`).
- `SUMMARY_POLISH_PASS` — enable the final prose-polish pass that may improve style but changes no facts, names, or event order (default `true`).
- `SUMMARY_POLISH_TEMPERATURE` — temperature for the polish pass (default `0.7`).
- `STYLE_RULES_FILE` / `ANTI_HALLUCINATION_FILE` / `VALIDATION_PROMPT_FILE` — the composable prompt parts (`prompts/style_rules.txt`, `prompts/anti_hallucination.txt`, `prompts/validation.txt`).
- `PHONETIC_CORRECTIONS_FILE` — ASR-error corrections table embedded into the per-session glossary (default `../OotD/.agent/skills/rpg-summarizer/resources/phonetic_corrections.md`; skipped gracefully if missing).
- `CONTEXT_DIR` — campaign context (entity wiki pages, `Campaign_Context.md`, `Timeline.md`) loaded at runtime; campaign facts are **not** baked into the prompts. **Recommended**: point this at an OotD checkout's `content/` directory (e.g. `CONTEXT_DIR=../OotD/content`) rather than copying context into rpgnotes — its layout (`02-People/`, `03-Locations/`, `04-Items-and-Loot/`, `05-Lore/`, plus `Campaign_Context.md`/`Timeline.md` at the root) is exactly what `build_session_glossary`/`load_context_files` expect, so campaign state is read live from the single source of truth instead of drifting out of sync.
- `TIMELINE_RECENT_SESSIONS` — only the last N `## Sesja` sections of `Timeline.md` are sent as AI context (default `10`; `0` = whole file). The full timeline grows unbounded and ancient sessions add nothing but tokens.

The pipeline writes per-session artifacts to `OUTPUT_DIR/assets/sessions/<NNN>/`: `transcript.txt`, `transcript.json`, `transcript_enriched.txt` (see below), `draft0.md` (the validated summary draft — the deliverable), `validation_report.md` (unresolved fact-check findings), `recording_start.txt` (Craig's recording start unix timestamp — the shared t=0 for all timeline sources) and `chat_events.{json,txt}` (see below).

## Foundry chat events (timeline-anchored)

The session `session<NN>.json` chat archive is distilled into `chat_events.json` + `chat_events.txt`: module noise (Tidbits/Plutonium banners) is dropped, HTML is flattened, dice rolls keep their formulas and totals via the structured Foundry/Beyond20 markup (`1d20 + 11 = 26`-style), and every message gets an `offset_secs` measured from **Craig's recording start** (parsed from `info.txt` inside the audio zip). That makes the transcript, the `[VISUAL]` screenshot anchors and the chat events all share one clock — a `[VISUAL 02:33:40]` scene and a `[02:33:40] Sydon (rzut): Cataclysmic Bolt…` chat line describe the same moment.

Both files sit in the session assets dir for on-demand lookups during OotD refinement.

## Enriched transcript (one time-sorted file)

All three timeline sources are merged into a single `transcript_enriched.txt` in the session assets dir, sorted by offset on the shared recording clock:

- speech segments (from `transcript.json`, same speaker-header format as `transcript.txt`),
- visual caption lines: `[VISUAL HH:MM:SS] caption` (`[VISUAL HH:MM:SS KEY] …` for key frames),
- chat event lines: `[CZAT HH:MM:SS] Speaker (rzut): text` for rolls, `[CZAT HH:MM:SS] Speaker: text` for plain chat. Events sent before the recording started appear at the very top as `[CZAT PRZED NAGRANIEM] …`.

At equal offsets visual lines come before chat lines. The file is built whenever at least one annotation source exists (screenshots-only, chat-only, or both — it degrades gracefully); with neither, the plain transcript is used and no file is written. The enriched transcript is what the summary generation **and** the validation pass consume — chat events reach the Gemini calls inline, with chunk-window locality keeping context bounded. Quote extraction/verification deliberately stays on the plain `transcript.txt` so quote candidates are always actually spoken lines.

## Handoff to the wiki (OotD)

rpgnotes is the "transcription + draft-0 factory": it runs unattended (audio → transcript → chunked, validated Gemini summary), and the interactive prose refinement, fact-checking, and wiki work happens in the sibling `OotD` repo via Claude Code sessions. The end-to-end flow:

```
audio (craig-*.flac.zip) + session*.json
  → rpgnotes: per-speaker transcription → combined transcript.txt
  → rpgnotes: chunked Gemini summary + validation pass
              → draft0.md + validation_report.md
  → OotD: /generate-session-recap-draft (refine mode, seeded with draft0.md)
  → OotD: /finalize-session-recap → wikilinks, images, timeline, final recap
```

There is no separate handoff/copy step: point `OUTPUT_DIR` directly at an OotD checkout's `content/` directory (e.g. `OUTPUT_DIR=/path/to/OotD/content`), and every artifact — `transcript.txt`, `transcript_enriched.txt`, `chat_log.json`, `chat_events.json`, `chat_events.txt`, `draft0.md`, `validation_report.md`, `quotes.json` — lands directly in `content/assets/sessions/<NNN>/`, exactly where `/generate-session-recap-draft` looks for it. rpgnotes no longer renders the final session note itself — structured details extraction and the final note assembly happen in OotD after the refine pass (only the manual workflow still renders the template locally).

## Session screenshots (optional visual context)

Capture the VTT screen during the session and the pipeline will interleave Gemini-captioned `[VISUAL HH:MM:SS] …` anchor lines into the transcript — hard evidence of scene changes, token positions, and handouts for the summarizer and fact-checker.

**Before the session starts** (alongside starting Craig), run on the host:

```bash
python3 scripts/capture_session.py
```

Pick the monitor showing the VTT (never the one with Discord — only the selected region is ever written to disk), leave it running, stop with `Ctrl+C` after the session. Frames land in `DOWNLOADS_DIR/screens_session/` as `shot_<unix_ts>.png` plus a `session_start.txt` timestamp; frames nearly identical to the previous kept one are dropped automatically.

Flags: `--interval N` (seconds between capture attempts, default 600 — D&D scenes change slowly and each kept frame costs a Gemini caption call, so 10 minutes is plenty; near-identical frames are still dropped immediately), `--monitor DP-1` / `--region WxH+X+Y` (skip the interactive picker), `--output-dir PATH`, `--dedupe-threshold F` (mean 0-255 gray diff, default 4.0), `--once` (single test frame).

Backends are auto-detected: `grim`+`slurp` (wlroots Wayland), the XDG desktop portal (GNOME Wayland; needs ImageMagick + `python3-dbus`/`python3-gi`), or `maim`/`scrot`/ImageMagick (X11). On GNOME Wayland, run this once so the portal stops asking for permission:

```bash
python3 scripts/capture_session.py --grant-portal-permission
```

(The GNOME portal briefly writes a full-desktop frame to your Pictures dir; the script crops it to your region and deletes the original immediately. GNOME may flash the screen on each capture — that's normal.)

**Ingestion** is enabled by setting `SCREENSHOTS_DIR` in `.env` (e.g. `./Downloads/screens_session`); leave it empty and the pipeline behaves exactly as before. Each kept frame gets one Gemini Flash multimodal caption (Polish, glossary-anchored; model via `VISUAL_CAPTION_MODEL`, defaults to `GEMINI_FLASH_MODEL`; per-frame captions cached in `TEMP_DIR`, resumable). Outputs land in `OUTPUT_DIR/assets/sessions/<NNN>/`: `visual_log.json` (`[{offset_secs, caption, path, is_key}]` — files named `shot_<ts>_key.png` are flagged as key moments); the captions are merged into `transcript_enriched.txt` (see the enriched transcript section), which is fed to the summarizer. `VISUAL_DEDUPE=false` disables the ingestion-side re-dedupe.

Offsets are anchored to Craig's recording start (`recording_start.txt`, parsed from the audio zip's `info.txt`) when available — this survives starting the capture script earlier or later than the recording. `session_start.txt` is only the fallback anchor. `VISUAL_CROP=WxH+X+Y` cuts system/browser chrome (dock, tabs, clock) out of both the AI upload and the dedupe signature; disk originals are never modified.

Key Whisper knobs:

- `WHISPER_MODEL` — `large-v3` by default; smaller variants (`small`, `medium`, `distil-large-v3`) are faster and lighter.
- `WHISPER_DEVICE` — `cuda` for GPU (NVIDIA or AMD), `cpu` to force CPU.
- `WHISPER_COMPUTE_TYPE` — `float16` (GPU), `int8_float16`, or `int8` (CPU).
- `WHISPER_VAD` — voice-activity-detection filter; `true` cuts silence and helps suppress hallucinations.

## Project layout

```
src/rpgnotes/
├── cli.py             argparse → pipeline functions
├── config.py          pydantic-settings, .env-driven
├── pipeline.py        full / transcription / manual workflows
├── chatlog.py         find newest session*.json, extract number+date
├── audio.py           unzip craig-*.flac.zip → per-speaker FLACs
├── speakers.py        Discord username → character name mapping
├── hallucination.py   blocklist of common Whisper subtitle hallucinations
├── helpers.py         small filesystem/JSON utilities
├── chatevents.py      distill Foundry chat log into timeline-anchored events
├── visual.py          screenshot dedupe/captioning ([VISUAL] entries)
├── enrich.py          merge speech + [VISUAL] + [CZAT] into one transcript
├── template.py        render template.md → final markdown (manual workflow)
├── transcribe/
│   ├── base.py        TranscriberProtocol + Segment shape
│   ├── faster.py      faster-whisper backend
│   ├── runner.py      skip-existing iteration over a FLAC dir
│   └── combine.py     merge per-speaker JSONs into a sorted transcript
└── summarize/
    ├── models.py      SessionData, QuotesData, ValidationReport (pydantic)
    ├── chunker.py     split transcript into ~800-line chunks at speaker turns
    ├── glossary.py    session glossary from context entities + phonetic fixes
    └── gemini.py      chunked map-reduce summary, validation pass,
                       quotes extraction, quote verification
```

## Development

```bash
pip install -e ".[dev]"
pytest
mypy src/
ruff check .
```

## Migrating from the old `main.py`

- Delete `models/large-v3.pt` — that file is the openai-whisper format. faster-whisper redownloads `Systran/faster-whisper-large-v3` (CT2 format) into the same `models/` directory on first run.
- `requirements.txt` and `requirements_amd.txt` are gone; everything lives in `pyproject.toml`.
- The interactive menu is still available via `./run.sh --menu`. The new default is non-interactive.
