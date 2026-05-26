# RPG Session Notes Automator

Turn a TTRPG session bundle — a `craig-*.flac.zip` of per-speaker audio plus a `session*.json` chat log — into a single Markdown session note with AI-generated summary, structured details, and quotes.

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

That's it. Files end up in `OUTPUT_DIR/01-Sessions/Sesja XX - <title>.md` and assets in `OUTPUT_DIR/assets/sessions/<NNN>/`.

## Commands

| Command | What it does |
|---|---|
| `./run.sh` | Full workflow: transcribe + Gemini summary/details/quotes for the newest session. |
| `./run.sh transcribe` | Transcription only (no Gemini calls). |
| `./run.sh manual` | Skip Gemini; paste summary/details/quotes JSON manually. |
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

All knobs live in `.env`. See [.env.example](.env.example) for the full list. Key Whisper knobs:

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
├── template.py        render template.md → final markdown
├── transcribe/
│   ├── base.py        TranscriberProtocol + Segment shape
│   ├── faster.py      faster-whisper backend
│   ├── runner.py      skip-existing iteration over a FLAC dir
│   └── combine.py     merge per-speaker JSONs into a sorted transcript
└── summarize/
    ├── models.py      SessionData, QuotesData (pydantic)
    └── gemini.py      generate_summary / _details / _quotes
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
