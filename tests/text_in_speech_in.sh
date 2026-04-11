#!/usr/bin/env bash
# Manual smoke test: speak into the mic and have `cai transcribe` write the
# recognized text to `input.txt`.
#
# Usage:
#   tests/text_in_speech_in.sh
#   (then read your stanza aloud; MicRecorder stops on trailing silence)
#
# Exercises the STT path end-to-end: microphone capture → Whisper → file.

set -euo pipefail

cd "$(dirname "$0")/.."

OUT="$(pwd)/input.txt"
rm -f "$OUT"

echo "── cai transcribe → $OUT ──────────────────────────────────────"
echo "Speak your stanza now. Recording stops after a short silence."
echo

rc=0
uv run cai --no-tts transcribe --output "$OUT" || rc=$?
echo "transcribe exit: $rc"

echo
echo "── captured text ───────────────────────────────────────────────"
if [[ -f "$OUT" ]]; then
    cat "$OUT"
else
    echo "(no file written at $OUT)"
fi
echo "────────────────────────────────────────────────────────────────"
