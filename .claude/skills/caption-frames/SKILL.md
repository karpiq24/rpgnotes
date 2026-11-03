---
name: caption-frames
description: Caption the session's map snapshots (Foundry recorder frames) inside this Claude Code session instead of Gemini - Haiku subagents first, Sonnet for frames Haiku gets wrong - and import the captions into the rpgnotes pipeline. Use when the user asks to caption/describe the session images or snapshots, or when ./run.sh stops with "map snapshot(s) need captions".
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

If it reports 0 frames, skip to step 4.

## 2. Haiku pass

Split `frames` into batches of about 8. Spawn one Agent per batch with `model: "haiku"`,
all in one message so they run in parallel. Give each one this brief, with the absolute folder path and the batch's
task entries pasted in:

> Read `<dir>/instructions.md` and follow it. For each frame below, Read the image
> `<dir>/<image>` and Write its caption (2-4 Polish sentences, nothing else) to
> `<dir>/<caption>`. Use the `hint` line as known facts. Describe only what is
> visible: no guesses ("może sugerować"), and include legible on-screen text
> (labels, inscriptions). Reply with just the list of files you wrote.
> Frames: <the batch's JSON entries>

## 3. Check Haiku's work, Sonnet where it falls short

Read every caption file. Then look at a sample of the images yourself: at least 5 frames,
including every handout (`key: true`) and frames from different scenes. Compare them with their captions.
A caption fails when it:
- names something that is not in the image, the hint or the glossary, or describes events,
- misreads visible text (handout title, scene name) or picks the wrong glossary name,
- is generic ("a fantasy map with tokens") where the image shows readable specifics,
- is not 2-4 Polish sentences, or contains commentary about the task.

Redo the failing frames with an Agent of `model: "sonnet"`, using the same brief.
If more than about a third of the sample fails, the problem is systematic:
redo every frame with Sonnet, not only the ones you checked. Re-check what Sonnet wrote the same way.

## 4. Import

```bash
./run.sh captions-import
```

This copies the captions to where the pipeline keeps them (`temp/visual_caption_<N>_<id>.txt`).
It exits non-zero and lists what is still missing if a caption file is empty or too long.
Fix those and import again.
After that, `./run.sh` continues with the AI notes.

Tell the user how many frames Haiku captioned, how many went to Sonnet and why,
and give one or two example captions.
