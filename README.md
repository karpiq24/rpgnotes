# RPG Session Notes Automator

Turn a TTRPG session bundle — a `craig-*.flac.zip` of per-speaker audio plus a `session*.json` chat log — into a **session package**: transcripts, chat events, a validated AI-drafted recap (`draft0.md`), its title and detail lists (`details.json`) and quotes, with a `manifest.json`. The wiki ([OotD](https://github.com/karpiq24/OotD)) imports the package and assembles the session note.

- **Transcription**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on CTranslate2 — AMD ROCm and NVIDIA CUDA both work.
- **Summarization**: Google Gemini (`gemini-4-argon` by default) via the `google-genai` SDK, with native structured output.
- **Record**: the RPG Notes Recorder Foundry module saves chat, rolls, scenes, combat, handouts and map snapshots by itself.
- **Run**: `./run.sh` after the game.

## Quick start

```bash
cp .env.example .env
$EDITOR .env                    # set GEMINI_API_KEY at minimum
./run.sh                        # first run builds the image, then shows the menu
```

That's it. Each session's package ends up in `OUTPUT_DIR/<NNN>/` (default `./output/`); in OotD, `/import-session <N>` picks it up from there. rpgnotes never writes into the wiki.

## Commands

| Command | What it does |
|---|---|
| `./run.sh capture` | Only without the Foundry module: screen capture during the game (runs on the host, `Ctrl+C` to stop). |
| `./run.sh` | After the game: shows the session it found and what's done, then a menu. `Enter` processes it. |
| `./run.sh status` | Only the status screen, then exit. |
| `./run.sh full` | Transcribe + Gemini draft/quotes, no questions (also the default when not in a terminal). |
| `./run.sh transcribe` | Transcription only (no Gemini calls). |
| `--fresh` | With any command: redo the session from scratch instead of resuming (re-transcribes, calls Gemini again). |

`./run.sh` checks `.env` and the mounted folders first, creates the ones this repo owns, and rebuilds the image quietly (log in `temp/build.log`).

## Day-to-day workflow

1. **The game:** start Craig with `/join` and accept the Foundry module's *Start recording* prompt (or click the record toggle). When you shut down the world, choose *Save and shut down*: `session<NN>.json` lands in your Downloads folder.
2. **After the game:** download the Craig `craig-*.flac.zip` into `DOWNLOADS_DIR` too, then `./run.sh` and press `Enter`.

The status screen looks like this:

```
════════════════════════════════════════════════════════════
  Sesja 81 · 2026-10-12
════════════════════════════════════════════════════════════
  Chat log     session81.json
  Audio        craig-abc.flac.zip, 412 MB
  Screenshots  37 frames
  Gemini       gemini-4-argon, flex tier

  Outbox       · transcript   · draft0.md   · details   · quotes
  Note         temp holds work for session 80; it is cleared when you start

  [1] Process session 81: transcribe + AI notes   (Enter)
  [2] Transcribe only (no Gemini cost)
  [q] Quit
```

Runs are resumable: stop with `Ctrl+C` at any point and the next run continues where it left off (the menu then says *Continue* and offers *Start over*). Work in `TEMP_DIR` is tagged with its session number (`temp/session.txt`) and cleared automatically when a new session comes in, so audio of the previous session can never leak into the next one; screenshots, logs and caches survive the clearing. The session's Craig zip is moved to `DOWNLOADS_DIR/_processed/` and its name recorded in `audio_source.txt`, so *Start over* reuses exactly that zip.

## Foundry recorder module

`foundry/rpgnotes-recorder/` is a Foundry VTT module (v13+, tested on v14 with dnd5e 6) that replaces both the chat archive macro and the screenshot script. It runs in the GM's browser only.

- **You start and stop it:** with the record toggle in the token controls (highlighted while recording), `/rpgnotes start` / `stop`, or a macro calling `game.modules.get("rpgnotes-recorder").api.start()` / `.stop()`. Saving downloads `session<NN>.json` (a normal browser download) and raises the session number by one.
- **It only suggests:** when 4 players are connected (setting) it asks whether to start ("Not now" mutes it for 15 min); when you *Return to Setup* or log out while recording it asks *Save and shut down* / *Keep recording for later* / *Cancel*; if all players disconnect it asks whether to save (rare, since tabs usually stay open after the game).
- **Nothing gets lost:** everything is kept in the browser's IndexedDB while recording, so a reload or crash resumes. An unsaved recording older than 30 minutes found when the world loads gets a *Save it now* / *Continue recording* / *Discard* prompt.
- **Recorded:** every chat message with dnd5e roll data (attack/save/damage/usage, item, formula, total, DC, crits, damage type), whispers marked as such, OOC/IC style; the active scene; combat start/rounds/turns/end; creatures dropping to 0 HP; images and journal pages shown to players (with the image and the page text); music changes.
- **Map snapshots:** a render of the map canvas only (no browser or Foundry UI), as the players see it (GM-only tokens hidden), every 10 minutes when it changed, on each scene change and combat start. Snapshots are skipped while the GM looks at a scene that isn't the active one.
- **Chat command** (GM): `/rpgnotes` status · `start` · `stop` (save now) · `key` (snapshot marked as a key moment) · `discard` · `number 85` (set the session number).
- **After saving** it offers to clear the chat log (a long log slows Foundry down).

The pipeline reads the file like the old chat export (same `title`/`archiveDate` keys): events become `[CZAT …]` lines in the enriched transcript, and the snapshots are unpacked to `TEMP_DIR/foundry_snapshots/` and captioned instead of `SCREENSHOTS_DIR`. The outbox copy (`chat_log.json`) keeps the snapshot metadata without the images. Old macro exports still work.

**Install:** in Foundry's setup screen, *Add-on Modules → Install Module*, paste the manifest URL `https://github.com/karpiq24/rpgnotes/releases/latest/download/module.json`, enable the module in the world, then set the next session number (`/rpgnotes number 85` or the module settings). **Release:** bump `version` and the `download` URL in `module.json`, run `foundry/build.sh`, and upload `foundry/dist/*` to a GitHub release `foundry-v<version>`.

## Podman / Fedora

`./run.sh` also works where `docker` is Podman (Fedora): under **rootless** Podman the entrypoint runs as container root — which *is* your host user — instead of dropping to `HOST_UID` (that would map to a subordinate uid and re-own the bind mounts). The compose file sets `label=disable` so SELinux lets the container read your home-dir bind mounts without relabeling them. Rootless Podman also refuses missing bind-mount sources; `./run.sh` creates the repo-owned ones and names any `.env` path that doesn't exist.

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
- `SUMMARY_TEMPERATURE` — temperature for the factual per-chunk summaries (default: empty = the model's default; Google recommends the default for Gemini 3+, lower values can cause looping).
- `SUMMARY_POLISH_PASS` — enable the final prose-polish pass that may improve style but changes no facts, names, or event order (default `false`: it is the most output-heavy call, and the draft is reviewed and edited by hand in the wiki anyway).
- `SUMMARY_POLISH_TEMPERATURE` — temperature for the polish pass (default: empty = model default).
- `GEMINI_PRO_MODEL` / `GEMINI_FLASH_MODEL` — `gemini-4-argon` (summary, polish, validation) and `gemini-3.8-flash` (details, quotes, screenshot captions).
- `GEMINI_THINKING_LEVEL` — thinking level for the summary/polish/validation calls: `low`, `medium` or `high` (default: empty = model default, `medium` on Argon; thinking is billed as output).
- `GEMINI_SERVICE_TIER` — `flex` (default; half price, each call may queue for minutes, falls back to `standard` when Flex is at capacity) or `standard`.
- `VALIDATION_MAX_PASSES` — validate → auto-fix rounds (default `1`; each round re-reads the whole transcript).
- Every Gemini call logs its input (cached), output and thinking tokens, and the run ends with per-model totals — check `cached` to confirm implicit caching kicks in across chunks.
- `STYLE_RULES_FILE` / `ANTI_HALLUCINATION_FILE` / `VALIDATION_PROMPT_FILE` / `DETAILS_PROMPT_FILE` / `QUOTES_PROMPT_FILE` — the prompts (`prompts/*.txt`). They hold no campaign facts: the party, names and campaign rules come from the campaign context.
- Every chunk call gets the party and the campaign's learned rules, the full session glossary (all canonical entity names + aliases + phonetic corrections) **and** the campaign background in its system prompt, plus the tail of the previous chunk for continuity. The glossary is deliberately not filtered by what the transcript contains — the names worth listing are exactly the ones the ASR mangles. The validation pass gets the glossary too, so it never "corrects" a canonical name back to its ASR spelling.
- `CAMPAIGN_CONTEXT_FILE` — the campaign context exported by the wiki (see below). Empty or missing = run without names, party, background or hotwords (the status screen says so); a file with an unknown `schema_version` stops the run.
- `TIMELINE_RECENT_SESSIONS` — only the last N timeline sessions are sent as AI context (default `10`; `0` = all). The full timeline grows unbounded and ancient sessions add nothing but tokens.

The pipeline writes each session to `OUTPUT_DIR/<NNN>/` — see the session package below.

## Foundry chat events (timeline-anchored)

The session `session<NN>.json` chat archive is distilled into `chat_events.json` + `chat_events.txt`: module noise (Tidbits/Plutonium banners) is dropped, HTML is flattened, dice rolls keep their formulas and totals via the structured Foundry/Beyond20 markup (`1d20 + 11 = 26`-style), and every message gets an `offset_secs` measured from **Craig's recording start** (parsed from `info.txt` inside the audio zip). That makes the transcript, the `[VISUAL]` screenshot anchors and the chat events all share one clock — a `[VISUAL 02:33:40]` scene and a `[02:33:40] Sydon (rzut): Cataclysmic Bolt…` chat line describe the same moment.

Both files go into the session package for on-demand lookups in the wiki.

## Enriched transcript (one time-sorted file)

All three timeline sources are merged into a single `transcript_enriched.txt` in the session assets dir, sorted by offset on the shared recording clock:

- speech segments (from `transcript.json`, same speaker-header format as `transcript.txt`),
- visual caption lines: `[VISUAL HH:MM:SS] caption` (`[VISUAL HH:MM:SS KEY] …` for key frames),
- chat event lines: `[CZAT HH:MM:SS] Speaker (rzut): text` for rolls, `[CZAT HH:MM:SS] Speaker: text` for plain chat. Events sent before the recording started appear at the very top as `[CZAT PRZED NAGRANIEM] …`.

At equal offsets visual lines come before chat lines. The file is built whenever at least one annotation source exists (screenshots-only, chat-only, or both — it degrades gracefully); with neither, the plain transcript is used and no file is written. The enriched transcript is what the summary generation **and** the validation pass consume — chat events reach the Gemini calls inline, with chunk-window locality keeping context bounded. Quote extraction/verification deliberately stays on the plain `transcript.txt` so quote candidates are always actually spoken lines.

## The wiki (OotD): two files, one each way

rpgnotes runs unattended (audio → transcript → chunked, validated Gemini summary → details and quotes); the review, wikilinks and images happen in the sibling [OotD](https://github.com/karpiq24/OotD) repo. The two repos share exactly two files, each with a `schema_version` both sides check:

```
OotD: scripts/export_context.py ──► campaign/campaign_context.json ──► rpgnotes (CAMPAIGN_CONTEXT_FILE)
rpgnotes ──► OUTPUT_DIR/<NNN>/ + manifest.json ──► OotD: /import-session <N> ──► review ──► /finalize-session-recap
```

**Campaign context** (`CAMPAIGN_CONTEXT_FILE`, read by `src/rpgnotes/campaign.py`): the party, every entity name with its aliases, phonetic (ASR) corrections, rules learned from the user's edits, Whisper hotwords, the campaign summary and the timeline. OotD regenerates it after every finalized session, so corrections made to one draft reach the next one. rpgnotes never reads the wiki itself.

**Session package** (`OUTPUT_DIR/<NNN>/`, described by `manifest.json` from `src/rpgnotes/manifest.py`):

| File | Kind | What |
|---|---|---|
| `transcript.txt`, `transcript.json` | publish | Combined per-speaker transcript |
| `transcript_enriched.txt` | publish | Transcript with `[VISUAL]`/`[CZAT]` lines (see above) |
| `chat_log.json`, `chat_events.{json,txt}` | publish | Foundry chat log and its timeline-anchored events |
| `visual_log.json` | publish | Screenshot captions |
| `quotes.json` | publish | Verified quotes |
| `draft0.md` | working | The validated narrative (`###` sections) |
| `details.json` | working | Title, key events, NPCs, locations, items (derived from the draft) |
| `validation_report.json` | working | Fact-check findings left for a human |

`publish` files end up next to the session note on the public site, `working` files stay private. `manifest.json` also says whether the package is `complete` (draft, details, quotes and transcript present). Other files in the folder (`recording_start.txt`, `audio_source.txt`) are rpgnotes' own bookkeeping. After an import OotD writes `.imported` there, which the status screen reads.

## Session screenshots (optional visual context)

With the Foundry recorder module this is not needed: its map snapshots are used instead. Without it, `./run.sh capture` grabs the VTT screen during the game and the pipeline captions each frame into `[VISUAL HH:MM:SS] …` lines; setup, backends and flags are in [docs/screen-capture.md](docs/screen-capture.md).

## Transcription

How transcription works: each speaker's Craig track is run through Silero VAD, the speech regions are grouped into ≤30 s clips on the **original** timeline, and each clip is decoded by faster-whisper with word timestamps. Segments are split at pauses longer than 1.5 s, so speaker turns interleave at the right moments in `transcript.txt`. (faster-whisper's own `vad_filter` concatenates all speech into one stream; segment timestamps then smear across the removed silence — a 3-word line could span 7 minutes and land far out of order.) The combine step drops a segment only when Whisper's own rule says the window was silent (no-speech AND low confidence), plus repetition loops and known subtitle hallucinations, and logs how many words each reason removed.

Key Whisper knobs:

- **Hotwords**, not a free-form prompt: the campaign's hotwords list (`hotwords` in the campaign context; OotD keeps it in `campaign/whisper_hotwords.txt`) is prepended to *every* decode window (an `initial_prompt` only reaches the first 30 s window when previous-text conditioning is off, and is cut to its last ~223 tokens). The budget is ~150 tokens (~25–30 names), so list only names the ASR gets wrong; the startup log prints the packed list.
- `WHISPER_HOTWORDS_RECENT_SESSIONS` — names linked in the last N timeline sessions fill the rest of the hotword budget, most-linked first (default `3`; `0` = file only).

- `WHISPER_MODEL` — `large-v3` by default; smaller variants (`small`, `medium`, `distil-large-v3`) are faster and lighter.
- `WHISPER_DEVICE` — `cuda` for GPU (NVIDIA or AMD), `cpu` to force CPU.
- `WHISPER_COMPUTE_TYPE` — `float16` (GPU), `int8_float16`, or `int8` (CPU).
- `WHISPER_VAD` — voice-activity-detection filter; `true` cuts silence and helps suppress hallucinations.

## Project layout

```
src/rpgnotes/
├── cli.py             commands + the interactive menu
├── status.py          what the menu shows: session found, inputs, progress
├── foundry.py         read the Foundry recorder module's session file
├── config.py          pydantic-settings, .env-driven
├── pipeline.py        full / transcription workflows
├── campaign.py        read + render the wiki's campaign_context.json
├── manifest.py        manifest.json of a session package
├── chatlog.py         find newest session*.json, extract number+date
├── audio.py           unzip the session's craig-*.flac.zip → per-speaker FLACs
├── speakers.py        Discord username → character name mapping
├── hallucination.py   blocklist of common Whisper subtitle hallucinations
├── helpers.py         small filesystem/JSON utilities
├── llm.py             google-genai client: text + structured calls, retries
├── chatevents.py      distill Foundry chat log into timeline-anchored events
├── visual.py          screenshot dedupe/captioning ([VISUAL] entries)
├── enrich.py          merge speech + [VISUAL] + [CZAT] into one transcript
├── transcribe/
│   ├── base.py        TranscriberProtocol + Segment shape
│   ├── faster.py      faster-whisper backend (VAD clips, word-level splits)
│   ├── hotwords.py    Whisper hotwords: file + recent Timeline names
│   ├── runner.py      skip-existing iteration over a FLAC dir
│   └── combine.py     merge per-speaker JSONs into a sorted transcript
└── summarize/
    ├── models.py      SessionData, QuotesData, ValidationReport (pydantic)
    ├── chunker.py     split transcript into ~800-line chunks at speaker turns
    ├── glossary.py    session glossary from context entities + phonetic fixes
    └── gemini.py      chunked map-reduce summary, validation pass,
                       quotes extraction, quote + speaker verification
```

## Development

```bash
pip install -e ".[dev]"
pytest
mypy src/
ruff check .
```
