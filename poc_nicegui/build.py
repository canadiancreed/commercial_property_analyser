"""Reproducible build of the Commercial Property Analyser desktop .exe (PyInstaller).

    python poc_nicegui/build.py            # onefile  (single file; slower first start)
    python poc_nicegui/build.py --onedir   # onedir   (a folder to zip; faster start)

Bundles NiceGUI, the project's json/ + config/ seed, the live properties.json seed, the
Playwright driver, and the app icon. The *target machine* still needs a Firefox browser
for the realtor.ca scraper:

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

ROOT   = Path(__file__).resolve().parents[1]          # project / worktree root
NGPKG  = Path(nicegui.__file__).parent
ICON   = ROOT / "poc_nicegui" / "icon.ico"
# Seed the bundled properties.json from the live repo-root file when present. In a
# worktree, ROOT is repo/.claude/worktrees/<name>, so the repo root is parents[2].
_live  = ROOT.parents[2] / "properties.json"
SEED   = _live if _live.exists() else ROOT / "properties.json"
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
        "--add-data", f"{SEED}{SEP}.",
    ]
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    cmd.append(str(entry))
    print("Running:", " ".join(cmd))
    rc = subprocess.call(cmd, env={**os.environ, "PYTHONPATH": str(ROOT)})
finally:
    entry.unlink(missing_ok=True)

sys.exit(rc)
