#!/usr/bin/env sh
# The regression suite, exactly as it should run before every push. No game, no Steam, no shared CI minutes:
# GitLab pipelines are deliberately not used for this project (2026-09-25).
set -e
cd "$(dirname "$0")/.."
uv sync --frozen --group dev --quiet
# The Lua half of the suite (50 files) runs the shipped runtime under liblua5.4 (ctypes) and lupa, and the
# fragment lint compiles each file with luac. Without them those tests SKIP, and a green run would say nothing
# about the runtime: refuse to run instead.
uv run --frozen python - <<'PY'
import ctypes.util, sys
missing = []
if not ctypes.util.find_library("lua5.4"):
    missing.append("liblua5.4 (Debian/Ubuntu: apt install liblua5.4-0)")
try:
    import lupa  # noqa: F401
except ImportError:
    missing.append("lupa (uv sync --group dev)")
import shutil
if not (shutil.which("luac5.4") or shutil.which("luac")):
    missing.append("luac (Debian/Ubuntu: apt install lua5.4; the fragment lint lists each file's globals)")
if missing:
    sys.exit("check.sh: the Lua tests would skip; install " + " and ".join(missing))
PY
exec uv run --frozen python -m pytest -q tests "$@"
