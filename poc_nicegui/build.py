"""Reproducible build of the Commercial Property Analyser desktop .exe (PyInstaller).

    python poc_nicegui/build.py            # onefile  (single file; slower first start)
    python poc_nicegui/build.py --onedir   # onedir   (a folder to zip; faster start)

Bundles NiceGUI, the project's json/ + config/ reference & config seed, the Playwright
driver, and the app icon. It does NOT bundle properties.json: the SQLite DB is the single
source of truth for property records, so a fresh install starts with an empty database
(import is a separate, explicit action). The *target machine* still needs a Firefox
browser for the realtor.ca scraper:

    python -m playwright install firefox

(Bundling the Firefox binary itself into the exe is not done yet — see poc_nicegui/TODO.md.)
Output: dist/CommercialPropertyAnalyser.exe (onefile) or dist/CommercialPropertyAnalyser/ (onedir).
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

import nicegui

# Project root = the nearest ancestor (including this file's own dir) that contains the
# poc_nicegui/ source. This lets build.py run from poc_nicegui/build.py OR from a copy
# dropped in the project's main folder next to the delivered .exe.
_here = Path(__file__).resolve()
ROOT = next((c for c in (_here.parent, *_here.parents)
             if (c / "poc_nicegui" / "app.py").exists()), _here.parents[1])
NGPKG  = Path(nicegui.__file__).parent
ICON   = ROOT / "poc_nicegui" / "icon.ico"
SEP    = ";" if os.name == "nt" else ":"
ONEFILE = "--onedir" not in sys.argv

# PyInstaller resolves imports from the entry script's directory, so build from a copy at
# the project root (where the data/ analysis/ scoring/ … packages live); PYTHONPATH too.
entry = ROOT / "_cpa_build_main.py"
shutil.copy(ROOT / "poc_nicegui" / "app.py", entry)
try:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "CommercialPropertyAnalyser",
        "--noconfirm", "--clean", "--windowed",
        "--onefile" if ONEFILE else "--onedir",
        "--collect-all", "playwright",
        "--add-data", f"{NGPKG}{SEP}nicegui",
        "--add-data", f"{ROOT / 'json'}{SEP}json",
        "--add-data", f"{ROOT / 'config'}{SEP}config",
    ]
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    cmd.append(str(entry))
    print("Running:", " ".join(cmd))
    rc = subprocess.call(cmd, env={**os.environ, "PYTHONPATH": str(ROOT)})
finally:
    entry.unlink(missing_ok=True)

sys.exit(rc)
