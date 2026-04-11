#!/usr/bin/env bash
# Manual smoke test: run `cai dialogue` end-to-end against real hardware.
#
# Usage:  tests/dialogue_smoke.sh
#
# What this exercises:
#   1. Both models load cleanly in one process.
#   2. File-watch → TTS path (new line in speak.txt → speaker output).
#   3. Mic → STT → file path (you speak → new line in listen.txt).
#   4. Shared inference lock serializes the two paths without deadlock.
#   5. Ctrl+C shutdown cleanly stops both the poller and the listener.
#   6. Echo/feedback behaviour on your current audio setup (headphones
#      vs open speakers — look for spurious entries in listen.txt that
#      match what was just spoken).
#
# This test is interactive. It will NOT fail automatically — you decide
# thumbs-up / thumbs-down after inspecting the two files at the end.

set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

SPEAK_FILE="$PROJECT_ROOT/tests/dialogue_smoke.speak.txt"
LISTEN_FILE="$PROJECT_ROOT/tests/dialogue_smoke.listen.txt"
: > "$SPEAK_FILE"
: > "$LISTEN_FILE"

cat <<EOF
── cai dialogue smoke test ─────────────────────────────────────
speak-file:  $SPEAK_FILE
listen-file: $LISTEN_FILE

In ANOTHER terminal, append lines to the speak-file to hear them:
    echo "Hello from the smoke test." >> $SPEAK_FILE

Speak into your mic; transcriptions will land in the listen-file:
    tail -f $LISTEN_FILE

Things to verify during the run:
  [ ] First speak-file line is spoken aloud within ~1s of appending.
  [ ] Speaking into the mic produces a line in listen-file.
  [ ] Speaking WHILE TTS is playing interrupts playback (barge-in).
  [ ] On headphones: no echo entries in listen-file from TTS output.
  [ ] On speakers: note whether TTS output gets re-transcribed
      (expected pre-P13; see BUGS.md).
  [ ] Ctrl+C returns to the shell without a stacktrace or hang.

Starting dialogue now. Press Ctrl+C when done.
────────────────────────────────────────────────────────────────
EOF

uv run cai dialogue \
    --speak-file "$SPEAK_FILE" \
    --listen-file "$LISTEN_FILE" || true

echo
echo "── speak-file contents ─────────────────────────────────────────"
cat "$SPEAK_FILE" || true
echo "── listen-file contents ────────────────────────────────────────"
cat "$LISTEN_FILE" || true
echo "────────────────────────────────────────────────────────────────"
echo
echo "Manual review:"
echo "  - Did every appended speak line play aloud?"
echo "  - Do listen-file entries match what you actually said?"
echo "  - Any echo/feedback entries? (TTS output re-transcribed)"
echo "  - Did Ctrl+C shut down cleanly without a hang?"
