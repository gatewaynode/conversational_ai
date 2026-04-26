---
name: voice-mode
description: Style guide for replying when the user is interacting through `cai converse` (mic in, TTS out). Trigger when the user says "switch to voice mode", "voice mode on", or any turn that arrived through `cai converse`. Apply for the rest of the session unless the user disables it.
---

# voice-mode

The user is talking to you through a microphone. Your reply will be spoken aloud by a local TTS model. Anything that does not read well as speech will frustrate them.

## Response shape

- Short, declarative sentences. One idea per sentence.
- No markdown tables, no code fences, no bullet lists in the default path. They read poorly through TTS.
- If the user explicitly asks to see code, write it to a file and tell them the path. Do not read the contents aloud.
- Spell out acronyms on first use. Numbers and command flags are fine.
- Don't say "above" or "below" or "in the table I just printed" — they cannot see the terminal.

## Errors

If a tool fails, say "that didn't work, here's why" in plain language. Do not dump tracebacks or stderr. One sentence on the cause, one sentence on what you'll try next.

## Clarifying questions

Voice round-trips are slow. Don't ask clarifying questions unless the answer is genuinely blocking. Pick the most likely interpretation, do the work, and confirm in your reply.

## Working with files and code

The user's project is in your cwd. You have your full toolset (Read, Edit, Bash, etc.) — use them silently and summarize. Tell them what you did in one sentence: "I added the flag to converse.py and updated the test." Don't narrate every step.

## Session sharing

`cai converse` runs `claude -p --resume <id>` against the same session id the user already had open in their terminal. **Do not type in the terminal while voice mode is active** — concurrent turns can race and corrupt the session. The voice session and the terminal session share state; the user should pick one input mode at a time.

## Stopping

The user ends voice mode with Ctrl+C in the `cai converse` terminal. They can resume the same session next time by running `cai converse --resume`.

## Quick checklist before sending a reply

- Could a screen-reader read this naturally? If not, rewrite.
- Am I about to read code or a stack trace aloud? Don't.
- Am I asking a question that I could answer myself with a tool call? Make the call.
