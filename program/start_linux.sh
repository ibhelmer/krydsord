#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .venv/bin/python ]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import tkinter, reportlab' >/dev/null 2>&1; then
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python app.py "$@"