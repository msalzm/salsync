#!/bin/zsh
# Finder follows the Desktop symlink before opening this launcher.
launcher_path=${0:A}
cd -- "${launcher_path:h}" || exit 1

if [[ ! -x salvenv/bin/python ]]; then
    print 'Salsync could not find salvenv/bin/python in the project folder.'
    read '?Press Return to close.'
    exit 1
fi

exec salvenv/bin/python - <<'PY'
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import webbrowser

url = "http://127.0.0.1:8765"
try:
    with urllib.request.urlopen(url + "/api/state", timeout=2) as response:
        state = json.load(response)
    running = isinstance(state, dict) and "tracks" in state and "job" in state
except (OSError, ValueError, urllib.error.URLError):
    running = False

if running:
    webbrowser.open(url)
else:
    executable = str(Path("salvenv/bin/python").absolute())
    os.execv(executable, [executable, "src/app.py"])
PY
