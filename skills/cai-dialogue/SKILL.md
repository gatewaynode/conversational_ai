---
name: cai-dialogue
description: Use this skill when the user asks for a continuous TTS↔STT loop where one file feeds the speaker and another file collects the listener — e.g. agent-to-agent voice handoff, voice scratchpad, or accessibility flows. Drives `cai dialogue`. For voice-conversing with Claude itself, use `voice-mode` + `cai converse` instead.
---

# cai-dialogue

`cai dialogue` runs two threads in one process:

- A **TTS watcher** tails `--speak-file`. Anything appended is spoken aloud.
- An **STT listener** records mic utterances and appends each one to `--listen-file`.

The two files form the contract. Anything that can write to the speak file can talk; anything that can read the listen file can hear.

## When to use this

- The user wants to drive voice from another process (an agent, a script, a journal).
- The user wants a "speak this, capture my reply" loop without the `claude -p` bridge that `cai converse` adds.
- Accessibility: read aloud whatever appears in a draft file while capturing dictation in another.

For voice-conversing with Claude itself, prefer the `voice-mode` skill plus `cai converse` — `dialogue` does not bridge to Claude.

## Invocation

```bash
cai dialogue --speak-file draft.md --listen-file notes.md
```

Both flags default to the `[dialogue]` section in the config file (`~/.config/conversational_ai/config.toml`) if omitted.

## Duplex modes (set in config under `[dialogue]`)

- `barge_in = true` — VAD rising edge cancels in-flight TTS the moment the user starts speaking. Mid-sentence interruption.
- `full_duplex = true` — mic stays hot during TTS playback. Open-speaker setups risk re-transcribing the speaker's own output. Headphones recommended.
- `barge_in = false`, `full_duplex = false` — half-duplex. Mic mutes while TTS plays, no interruption. Safest default for desktop speakers.

The combinations matter:

- `barge_in=true full_duplex=true` — most natural conversation, headphones only.
- `barge_in=true full_duplex=false` — half-duplex with interruption (mic opens between TTS chunks).
- `barge_in=false full_duplex=false` — strict half-duplex (most predictable).
- `barge_in=false full_duplex=true` — rarely useful; mic captures TTS playback.

## Wake-word gating

Same five flags as `cai listen` and `cai converse`: `--wake-word WORD`, `--no-wake-word`, `--wake-timeout SECONDS`, `--include-trigger/--strip-trigger`, `--wake-alert/--no-wake-alert`. Mutex: `--wake-word X --no-wake-word` is rejected.

## Prerequisites

- `cai` on PATH (`./install.sh` installs the shim at `~/.local/bin/cai`).
- TTS model + STT model both available locally (defaults: Kokoro + Whisper).
- Mic and speakers (or headphones).

## Stopping

Ctrl+C in the `cai dialogue` terminal stops both threads cleanly within ~5s. You cannot send Ctrl+C for the user — start the command, then tell them how to stop it.

## Common mistakes

- Pointing both processes at the same file: don't. Speak file is one direction (write→speak), listen file is the other (mic→write).
- Running `cai dialogue` and `cai converse` against the same session: don't. They share STT/TTS hardware and the inference lock would serialise oddly.
