#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec uv run --env-file .env .venv/bin/python -m uvicorn brain.main:app --host 127.0.0.1 --port 8000 --no-access-log --log-level warning
