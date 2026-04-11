#!/usr/bin/env bash
# Manual smoke test: feed a stanza of the Iliad through `cai speak` and
# listen for TTS output on the default audio device.
#
# Usage:  tests/text_in_speech_out.sh
#
# The stanza is the opening invocation of Book I of the Iliad
# (Richmond Lattimore's translation) — a well-loved ~70-word passage
# with enough commas and line breaks to exercise TTS prosody.

set -euo pipefail

cd "$(dirname "$0")/.."

STANZA="Sing, goddess, the anger of Peleus' son Achilleus
and its devastation, which put pains thousandfold upon the Achaians,
hurled in their multitudes to the house of Hades strong souls
of heroes, but gave their bodies to be the delicate feasting
of dogs, of all birds, and the will of Zeus was accomplished."

echo "── Iliad, Book I (opening) ─────────────────────────────────────"
echo "$STANZA"
echo "────────────────────────────────────────────────────────────────"
echo "Speaking via: cai speak --no-stt (STT load skipped for speed)"
echo

uv run cai --no-stt speak "$STANZA"
