#!/usr/bin/env bash
# Launch MicroCompta on macOS / Linux.
set -e
cd "$(dirname "$0")"
if [ ! -f ".venv/.deps-ok" ]; then
    if [ ! -x ".venv/bin/python" ]; then
        echo "Creating virtual environment..."
        python3 -m venv .venv
    fi
    ./.venv/bin/python -m pip install --upgrade pip -q
    ./.venv/bin/python -m pip install -r requirements.txt
    touch .venv/.deps-ok
fi
exec ./.venv/bin/python -m microcompta
