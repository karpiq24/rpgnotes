---
name: caption-frames
description: Caption the session's map snapshots (Foundry recorder frames) inside this Claude Code session instead of Gemini, with parallel Sonnet subagents, and import the captions into the rpgnotes pipeline. Use when the user asks to caption/describe the session images or snapshots, or when ./run.sh stops with "map snapshot(s) need captions".
---

# Caption map snapshots in Claude Code

With `VISUAL_CAPTIONER=claude` in `.env` the pipeline makes no caption API calls.
It stops before the AI notes until every exported frame has a caption.
Work from the repo root.

## 1. Export

```bash
./run.sh captions-export
```

This writes `temp/claude_captions/` (TEMP_DIR from `.env`, `./temp` by default):
- `instructions.md`: the caption prompt, the campaign glossary and the output format.
- `tasks.json`: `{"session": N, "frames": [{"id", "image", "caption", "offset", "key", "hint"}]}`.
  Paths are relative to that folder. `hint` is what Foundry knew (scene name, handout title).
- `frames/*.jpg`: only the frames that still have no caption.

If it reports 0 frames, skip to step 3.

## 2. Caption with Sonnet

Split `frames` into batches of about 8. Spawn one Agent per batch with `model: "sonnet"`, all
in one message so they run in parallel. Give each one this brief, with the absolute folder path
and the batch's task entries pasted in:

> Read `<dir>/instructions.md` and follow it. For each frame below, Read the image
> `<dir>/<image>` and Write its caption (2-4 Polish sentences, nothing else) to
> `<dir>/<caption>`. Use the `hint` line as known facts. Describe only what is
> visible: no guesses ("może sugerować"), and include legible on-screen text
> (labels, inscriptions). Reply with just the list of files you wrote.
> Frames: <the batch's JSON entries>

Do not review the captions against the images: Sonnet's output is used as written.

## 3. Import

```bash
./run.sh captions-import
```

This copies the captions to where the pipeline keeps them (`temp/visual_caption_<N>_<id>.txt`).
If a caption file is missing, empty or too long, the command exits non-zero and lists those frames.
Re-run Sonnet for just those frames, then import again.
After that, `./run.sh` continues with the AI notes.

Tell the user how many frames were captioned and quote one example caption.
