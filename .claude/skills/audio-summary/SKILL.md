---
name: audio-summary
description: Use this skill when the user asks for spoken status pips while you work — phrases like "give me audio summaries", "say a quick summary when you finish a section", "speak a status update before you ask me anything", or "I want audio cues while you do this". Drives one-shot `cai speak` calls at section boundaries and before idling for input.
---

# audio-summary

A short spoken status pip you trigger from the terminal — not a continuous voice mode. The user's eyes are elsewhere and they want their ears to know when something finishes or when you're about to wait on them.

## Invocation

```bash
cai speak "Refactor done. Tests pass. Ready for review."
```

`cai speak "<text>"` is synchronous: it loads / reuses the TTS model, generates audio, plays it through the default output device, and exits. The positional-argument form is preferred. If the text contains awkward quoting (lots of apostrophes, embedded code), pipe it instead:

```bash
echo "Pulled the migration apart. Two questions before I continue." | cai speak -
```

## When to fire

Two situations:

1. **After a discrete unit of work** — a build went green, a refactor landed, a test suite finished, a file was written. One pip per section, not per file.
2. **Before going idle for user input** — when your next move is "wait for the user to tell me what to do," surface a pip first so they know you're parked, not still working.

Don't fire mid-task. Don't fire on every tool call. Don't fire to acknowledge an instruction you just received.

## Length budget

≤ 2 sentences. Aim for ≤ 10 seconds of audio. Long-form details belong in the chat transcript where the user can scroll back; the pip exists to grab attention, not to convey content.

## Don't fire during `cai converse`

If the user is in `cai converse`, every reply you produce is already being voiced through the bridge. Adding a `cai speak` would talk over it and make a mess of the audio device. Skip the pip when converse is active. If you're not certain, skip — the cost of a missed pip is much smaller than the cost of crosstalk.

## Don't read code or stack traces aloud

Same constraint as voice-mode: code, file paths longer than a few segments, and tracebacks read terribly through TTS. If you're announcing a failure, name the file and a one-sentence cause; the details stay in the chat transcript. "Got an import error in converse.py — wrong module name." is fine. The traceback is not.

## Failure handling

`cai speak` is best-effort. The TTS model may not be loaded, the audio device may be busy, the user may have muted the system. Treat any non-zero exit from `cai speak` as a silent no-op and continue your actual work. Do not surface the error to the user unless they specifically asked you to debug audio.

## Prerequisites

- `cai` on PATH. The repo's `install.sh` puts the shim at `~/.local/bin/cai`.
- A TTS model available locally (default: Kokoro). The first pip will pay the model-load cost; subsequent pips are fast.
- Speakers or headphones. The pip is useless if the user can't hear it — but you have no way to verify this from a tool call, so just send and continue.
