#!/usr/bin/env bash
# Builds the portable Windows desktop app:  dist/AuthorsHand-Windows.zip
#   AuthorsHand/
#     AuthorsHand.exe          ← double-click (Go launcher, no console window)
#     AuthorsHand.ico
#     Repair AuthorsHand.cmd   ← reinstalls the private Python environment
#     READ ME FIRST.txt
#     runtime/uv.exe            ← installs Python + libraries on first start (from PyPI wheel)
#     app/                      ← the Streamlit app + engine
# Usage: bash desktop/build_desktop.sh [windows|linux]   (linux = local test build)
set -euo pipefail
TARGET="${1:-windows}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/desktop/dist"
STAGE="$OUT/AuthorsHand"
rm -rf "$STAGE" && mkdir -p "$STAGE/runtime" "$STAGE/app"

# 1. launcher
( cd "$ROOT/desktop/launcher"
  if [ "$TARGET" = windows ]; then
    GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-H windowsgui -s -w" -o "$STAGE/AuthorsHand.exe" .
  else
    CGO_ENABLED=0 go build -trimpath -o "$STAGE/AuthorsHand" .
  fi )

# 2. uv runtime (taken from the official PyPI wheel)
TMP="$(mktemp -d)"
if [ "$TARGET" = windows ]; then PLAT=win_amd64; BIN=uv.exe; else PLAT=manylinux_2_17_x86_64; BIN=uv; fi
pip download uv --only-binary=:all: --platform "$PLAT" --no-deps -d "$TMP" -q
python3 - "$TMP" "$STAGE/runtime" "$BIN" <<'PY'
import sys, zipfile, glob, os
whl = glob.glob(os.path.join(sys.argv[1], "uv-*.whl"))[0]
with zipfile.ZipFile(whl) as z:
    name = next(n for n in z.namelist() if n.endswith("/scripts/" + sys.argv[3]) or n.endswith("/" + sys.argv[3]) and ".data/scripts/" in n)
    out = os.path.join(sys.argv[2], sys.argv[3])
    open(out, "wb").write(z.read(name)); os.chmod(out, 0o755)
print("uv:", name)
PY
rm -rf "$TMP"

# 3. app files
cp -r "$ROOT/app.py" "$ROOT/ui" "$ROOT/authorshand" "$ROOT/demo_data" "$ROOT/.streamlit" \
      "$ROOT/requirements-desktop.txt" "$ROOT/README.md" "$STAGE/app/"
find "$STAGE/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$ROOT/desktop/AuthorsHand.ico" "$STAGE/"
cp "$ROOT/desktop/READ ME FIRST.txt" "$STAGE/"
printf '@echo off\r\necho Repairing Authors Hand (reinstalls its private Python environment)...\r\nstart "" "%%~dp0AuthorsHand.exe" --repair\r\n' > "$STAGE/Repair AuthorsHand.cmd"

if [ "$TARGET" = windows ]; then
  ( cd "$OUT" && rm -f AuthorsHand-Windows.zip && zip -rq AuthorsHand-Windows.zip AuthorsHand )
  ls -la "$OUT/AuthorsHand-Windows.zip"
fi
echo "built $TARGET → $STAGE"
