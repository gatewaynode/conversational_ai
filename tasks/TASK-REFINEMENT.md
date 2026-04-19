# Feature 3 — Refinement questions

Plan file: `/Users/john/.claude/plans/stateful-stirring-pixel.md`

Answer inline under each question. Leave the **Proposed** line if you agree
with my default; edit/replace with your answer if you want something
different. Add free-form notes under **Notes:** for anything extra.

---

## 0. Re-scoping Feature 3

The existing TODO §Feature 3 (tasks/TODO.md:390-442) ships two skills +
installer. It does **not** include the runtime that makes voice
conversation with Claude actually work. Proposed: add a new **3.0 `cai
converse` subcommand** before the existing 3.1-3.5, and add a new
`voice-mode` skill to 3.1.

**Proposed:** Accept the resequencing — add 3.0 for `cai converse`, expand
3.1 from 2 skills to 3 (add `voice-mode`). Everything from 3.2 onward is
unchanged.

**Your answer:** This is a good proposal, lets go with it.

**Notes:**

---

## 1. Backend for the bridge

How should `cai converse` talk to the LLM?

- **A.** `claude -p` headless (spawns the Claude Code CLI as a subprocess
  per turn). Keeps the user's Claude Code auth, settings, plugins, and
  **full tool access** — file reads, git, bash, etc. The user is
  conversing with the *same* Claude Code they use in a terminal, just by
  voice.
- **B.** Direct Anthropic API via the `anthropic` Python SDK. Faster,
  cleaner streaming, no process-spawn overhead. But **no tool access** —
  this is pure chat, no file reads, no git.
- **C.** Ship both with a flag (`--backend claude|api`, default `claude`).
  Roughly doubles the code but gives users the choice.

**Proposed:** A — `claude -p` headless. Matches "converse with the full
Claude Code experience by voice." Note B as a future opt-in.

**Your answer:** I think option "A" would work as long as we make sure it is attached to the session the session the skill is triggered in, so `claude -p "Some prompt" --session-id`.  So we may need to catpure the session earlier and do some validation each time to make sure the session is still valid.  The default behavior of an session becoming invalid should be to terminate the processes cleanly.

**Notes:**

---

## 2. Subcommand name

- **A.** `cai converse` — unambiguous, matches the `dialogue` verb form.
- **B.** `cai chat` — shorter, more common.
- **C.** `cai talk` — shortest, most conversational.
- **D.** Something else:

**Proposed:** A (`converse`).

**Your answer:**  You are right and insightful, yes "converse" is better and matches the application name.  Good call.

**Notes:**

---

## 3. Skills to author in 3.1

- **A.** All three: `voice-mode` (the one Claude auto-loads during
  `cai converse`), `cai-dictation` (Claude invokes `cai transcribe`/`cai
  listen` on user's behalf in text mode), `cai-dialogue` (another agent
  drives `cai dialogue`).
- **B.** Just `voice-mode` — ship the primary-goal skill first, defer the
  other two until we know they're needed.
- **C.** Two: `voice-mode` + `cai-dictation`. Drop `cai-dialogue` (niche;
  the target audience is unclear).

**Proposed:** A — all three. SKILL.md files are ~60 lines each, cheap to
author; better to ship the full set once.

**Your answer:**  Yes, let's build and ship all 3.

**Notes:**

---

## 4. Session persistence

Should `cai converse` remember the Claude session across runs?

- **A.** In-memory only. Each `cai converse` starts a fresh Claude
  session. Simplest; matches how most chat tools work.
- **B.** Persist session id to
  `~/.local/state/conversational_ai/session` (or similar) so a user can
  exit, return, and keep the conversation going.
- **C.** Flag-driven: `--resume` on the subcommand to pick up the last
  session; default is fresh.

**Proposed:** A (in-memory only) for v1. B/C as clean follow-ups if users
want it.

**Your answer:** We should support all 3 persistence methods.

**Notes:**

---

## 5. Streaming vs blocking

v1 blocks on Claude's full response before TTS starts (subprocess
returns, we speak the whole thing). v2 could stream tokens and speak
sentence-by-sentence as they arrive.

**Proposed:** Block in v1. Note streaming as a future enhancement. For
most responses (a few sentences) the perceived latency is acceptable.

**Your answer:**  Agreed, start simple with the v1 blocking.  Note in the roadmap that streaming would be a good next goal.

**Notes:**

---

## 6. Interrupt / stop by voice

Ctrl+C works. Should "say 'stop'" also interrupt Claude mid-response?

**Proposed:** Not in v1. Barge-in (VAD cancels in-flight TTS) already
gives a partial stop. Voice-command stop is a separate feature worth
scoping later if wanted.

**Your answer:**  Yes, not in v1.  Add to roadmap.

**Notes:**

---

## 7. Working directory

`cai converse` spawns `claude` in the current working directory, so
Claude's file tools see whatever project you `cd`'d into. Same convention
as running `claude` directly.

**Proposed:** Keep this behavior. Document it in the help text and
SKILL.md.

**Your answer:** Agreed, keep this behavior.

**Notes:**

---

## 8. Anything else?

Free-form: anything about Feature 3 you want me to reconsider, add, or
remove before coding starts?

**Notes:** Nope.
