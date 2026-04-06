#!/usr/bin/env bash
# install.sh — install conversational-ai to ~/.local/share and create ~/.local/bin/cai
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/conversational_ai"
MLXAUDIO_SRC="$(cd "$SCRIPT_DIR/../mlx-audio" 2>/dev/null && pwd || true)"
MLXAUDIO_DST="$HOME/.local/share/mlx-audio"
BIN_DIR="$HOME/.local/bin"
ENTRY="$BIN_DIR/cai"

die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }
log() { printf '  → %s\n' "$*"; }

echo "conversational-ai installer"
echo "==========================="

# ── preflight ─────────────────────────────────────────────────────────────────

command -v uv >/dev/null 2>&1 \
    || die "uv not found — install from https://docs.astral.sh/uv/"

command -v rsync >/dev/null 2>&1 \
    || die "rsync not found — install via: brew install rsync"

[[ -n "$MLXAUDIO_SRC" && -d "$MLXAUDIO_SRC" ]] \
    || die "mlx-audio not found at $SCRIPT_DIR/../mlx-audio"

# ── copy app source ───────────────────────────────────────────────────────────

log "Copying app to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='install.sh' \
    --exclude='tasks/' \
    --exclude='tests/' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"

# ── copy mlx-audio alongside ──────────────────────────────────────────────────
# The pyproject.toml references mlx-audio as path = "../mlx-audio".
# Placing it at ~/.local/share/mlx-audio preserves that relative path from
# the install directory.

log "Copying mlx-audio to $MLXAUDIO_DST"
mkdir -p "$MLXAUDIO_DST"
rsync -a --delete \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    "$MLXAUDIO_SRC/" "$MLXAUDIO_DST/"

# ── install Python dependencies ───────────────────────────────────────────────

log "Installing Python dependencies"
(cd "$INSTALL_DIR" && uv sync --frozen --no-dev)

# ── entry script ──────────────────────────────────────────────────────────────

mkdir -p "$BIN_DIR"
cat > "$ENTRY" << EOF
#!/usr/bin/env bash
exec uv run --directory "$INSTALL_DIR" python main.py "\$@"
EOF
chmod +x "$ENTRY"
log "Created entry script at $ENTRY"

# ── PATH hint ─────────────────────────────────────────────────────────────────

echo ""
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "Note: $BIN_DIR is not in your PATH."
    echo "Add this to ~/.zshrc or ~/.bashrc:"
    echo ""
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

echo "Done. Run: cai"
echo "       Or: cai --help"
