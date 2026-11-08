"""Reproducible build of the Commercial Property Analyser desktop .exe (PyInstaller).

    python poc_nicegui/build.py            # onefile  (single file; slower first start)
    python poc_nicegui/build.py --onedir   # onedir   (a folder to zip; faster start)

Bundles NiceGUI, the embedded shipped data (the data/seeds package — v5.0.0 replaced the
json/ + config/ files), the Playwright driver, and the app icon. It bundles no property
data: the SQLite DB is the single source of truth, so a fresh install starts with an empty
database that seeds its reference data from data/seeds on first run (property import is a
separate, explicit action). The *target machine* still needs a Firefox
browser for the realtor.ca scraper:

    python -m playwright install firefox

(Bundling the Firefox binary itself into the exe is not done yet — see poc_nicegui/TODO.md.)
Output: the exe is written straight to the PROJECT ROOT (CommercialPropertyAnalyser.exe for
onefile; a CommercialPropertyAnalyser/ folder for onedir), so the copy you launch is always
the latest — no stale dist/ copy. PyInstaller's scratch (build dir + .spec) goes to the
system temp dir, so nothing else is left in the repo.
"""
import os
import sys
import shutil
import tempfile
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
# Build output goes to the project ROOT; PyInstaller's scratch (work dir + .spec) goes to
# the system temp so the only thing the build leaves in the repo is the exe itself.
SCRATCH = Path(tempfile.gettempdir()) / "cpa_pyinstaller"

# Pre-flight: on Windows a running copy of the app locks its own .exe, so PyInstaller fails
# late with a cryptic "[WinError 5] Access is denied". Detect it up front and say so plainly.
_out_exe = ROOT / ("CommercialPropertyAnalyser.exe" if ONEFILE
                   else "CommercialPropertyAnalyser/CommercialPropertyAnalyser.exe")
if _out_exe.exists():
    try:
        with open(_out_exe, "ab"):   # opening a running exe for write is denied on Windows
            pass
    except PermissionError:
        sys.exit(f"ERROR: '{_out_exe}' is in use — a copy of the app is still running. "
                 f"Close the Commercial Property Analyser app (and any Explorer window or "
                 f"antivirus scan holding it), then rebuild.")

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
        # v5.0.0: all shipped data is embedded in the data/seeds package (data-as-code),
        # not json/ + config/ files. seeds is imported lazily (from data import seeds inside
        # functions), so force-collect its submodules to guarantee they land in the exe.
        "--collect-submodules", "data.seeds",
        "--distpath", str(ROOT),                 # exe lands at the project root
        "--workpath", str(SCRATCH / "build"),    # scratch out of the repo (system temp)
        "--specpath", str(SCRATCH),
    ]
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    cmd.append(str(entry))
    print("Running:", " ".join(cmd))
    rc = subprocess.call(cmd, env={**os.environ, "PYTHONPATH": str(ROOT)})
finally:
    entry.unlink(missing_ok=True)

sys.exit(rc)
