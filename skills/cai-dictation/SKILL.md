---
name: cai-dictation
description: Use this skill when the user asks you to dictate, take voice notes, capture spoken input to a file, or "transcribe what I'm about to say". Drives `cai transcribe` (one utterance) or `cai listen` (continuous append) on their behalf.
---

# cai-dictation

The `cai` CLI ships two STT-only entry points. Pick the right one based on whether the user wants a single line or an ongoing session.

## When to use which

- **`cai transcribe`** — single utterance. Records once, transcribes, prints to stdout (or appends to a file with `-o`), exits. Use for "transcribe the next thing I say" or "take down this one note".
- **`cai listen FILE`** — continuous. Records every utterance and appends a line to FILE. Runs until Ctrl+C. Use for "dictate to notes.md" or "I'm going to talk for a while, capture it all".

If unsure, prefer `cai listen` — the user can always Ctrl+C after one line.

## Invocations

```bash
cai transcribe                    # one utterance → stdout
cai transcribe -o notes.md        # one utterance → append to notes.md
cai listen notes.md               # continuous → append each utterance to notes.md
```

## Wake-word gating (optional)

Both subcommands inherit the same five wake-word flags: `--wake-word WORD`, `--no-wake-word`, `--wake-timeout SECONDS`, `--include-trigger/--strip-trigger`, `--wake-alert/--no-wake-alert`. `cai transcribe` accepts them but they're rarely useful for a single shot — wake-word matters most for `cai listen` in a noisy room.

Note: `cai transcribe` does NOT currently take wake-word flags. Only `cai listen`, `cai dialogue`, and `cai converse` do. If the user wants gated single-shot capture, run `cai listen FILE --wake-word WORD` and tell them to Ctrl+C after their first utterance.

## Mic tuning

If transcriptions are noisy or cut off mid-word, the user can tune VAD with `--mic-threshold`, `--mic-silence`, `--mic-min-speech`, or pass `--calibrate-noise` to sample room tone at startup. Most users won't need these.

## Prerequisites

- `cai` must be on PATH. The repo's `install.sh` puts the shim at `~/.local/bin/cai`.
- A working microphone and an mlx-audio STT model (default Whisper) cached locally.

## You cannot stop a continuous run

`cai listen` blocks until Ctrl+C. You can start it for the user but you cannot send Ctrl+C from a tool call — tell them explicitly: "I've started `cai listen notes.md` — press Ctrl+C in that terminal when you're done."

## File paths

A relative FILE argument is relative to the cwd you run `cai` in. If the user asks to dictate to `notes.md` and you're not sure where they want it, ask once or default to the project root.
