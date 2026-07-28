#!/usr/bin/env bash
#
# Installs just the codeguard CLI. For a full setup (cluster + secrets + CLI)
# use ../../install.sh at the repository root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${CLI_TARGET:-/usr/local/bin/codeguard}"
TARGET_DIR="$(dirname "$TARGET")"

[ -f "$SCRIPT_DIR/codeguard.sh" ] || { echo "codeguard.sh not found next to this script" >&2; exit 1; }
[ -d "$TARGET_DIR" ] || { echo "$TARGET_DIR does not exist" >&2; exit 1; }

# `install` sets the mode atomically, unlike the old cp + cd + rm + mv dance
# (which left the destination missing if it was interrupted).
if [ -w "$TARGET_DIR" ]; then
    install -m 0755 "$SCRIPT_DIR/codeguard.sh" "$TARGET"
else
    echo "$TARGET_DIR requires elevated permissions; using sudo"
    sudo install -m 0755 "$SCRIPT_DIR/codeguard.sh" "$TARGET"
fi

echo "installed $TARGET ($("$TARGET" -v))"
command -v codeguard >/dev/null 2>&1 \
    || echo "note: $TARGET_DIR is not on your PATH"
