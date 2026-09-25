#!/usr/bin/env sh
# The regression suite, exactly as it should run before every push. No game, no Steam, no shared CI minutes:
# GitLab pipelines are deliberately not used for this project (2026-09-25).
set -e
cd "$(dirname "$0")/.."
uv sync --frozen --group dev --quiet
exec uv run --frozen python -m pytest -q tests "$@"
