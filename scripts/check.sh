#!/usr/bin/env sh
# The regression suite, exactly as it should run before every push. No game, no Steam, no shared CI minutes:
# GitLab pipelines are deliberately not used for this project (2026-09-25).
set -e
cd "$(dirname "$0")/.."
# uv when present; otherwise the venv from docs/AGENT_INSTALL.md section 4 (python3 -m venv + pip), as on SteamOS.
if command -v uv >/dev/null 2>&1; then
    uv sync --frozen --group dev --quiet
    PY="uv run --frozen python"
elif [ -x .venv/bin/python ]; then
    PY=".venv/bin/python"
else
    echo "check.sh: no uv and no .venv; see docs/AGENT_INSTALL.md section 4" >&2; exit 1
fi
# The Lua half of the suite (50 files) runs the shipped runtime under liblua5.4 (ctypes) and lupa, and the
# fragment lint compiles each file with luac. Without them those tests SKIP, and a green run would say nothing
# about the runtime: refuse to run instead.
$PY - <<'PY'
import ctypes.util, sys
missing = []
if not ctypes.util.find_library("lua5.4"):
    missing.append("liblua5.4 (Debian/Ubuntu: apt install liblua5.4-0)")
try:
    import lupa  # noqa: F401
except ImportError:
    missing.append("lupa (uv sync --group dev, or pip install -e . --group dev)")
import shutil
if not (shutil.which("luac5.4") or shutil.which("luac")):
    missing.append("luac (Debian/Ubuntu: apt install lua5.4; the fragment lint lists each file's globals)")
if missing:
    sys.exit("check.sh: the Lua tests would skip; install " + " and ".join(missing))
PY
# The linter first: pyflakes, bugbear and warnings only (pyproject [tool.ruff.lint]); the layout rules stay off,
# the code is deliberately dense. Fixable findings: `uv run ruff check --fix harness scripts tests`.
$PY -m ruff check harness scripts tests
exec $PY -m pytest -q tests "$@"
