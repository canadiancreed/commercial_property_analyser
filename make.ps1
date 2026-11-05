# Commercial Property Analyser - dev task runner for Windows PowerShell.
# Mirrors the Makefile targets without needing `make` installed.
#
#   .\make.ps1 build          # compile the .exe into dist\
#   .\make.ps1 run            # launch the desktop app (native window)
#   .\make.ps1 web            # browser mode (http://localhost:8080)
#   .\make.ps1 test           # run the test suite
#   .\make.ps1 fetch-rates    # refresh the Bank of Canada base rate
#   .\make.ps1 clean          # remove build\ dist\ *.spec
#
# Uses the `py` launcher by default (reliable on Windows); override with:
#   .\make.ps1 build -PY python
param(
    [Parameter(Position = 0)][string]$Target = "help",
    [string]$PY = "py"
)

$ErrorActionPreference = "Stop"

switch ($Target) {
    "run"           { & $PY poc_nicegui/app.py }
    "web"           { $env:CPA_WEB = "1"; & $PY poc_nicegui/app.py }
    "build"         { & $PY poc_nicegui/build.py }
    "compile"       { & $PY poc_nicegui/build.py }
    "test"          { & $PY -m pytest -q }
    "fetch-rates"   { & $PY scripts/fetch_interest_rates.py }
    "fetch-vacancy" { & $PY scripts/fetch_geographic_crosswalk.py; & $PY scripts/fetch_vacancy_rates.py }
    "clean"         { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, *.spec }
    default {
        Write-Host "Targets:"
        Write-Host "  .\make.ps1 run            launch the desktop app (native window)"
        Write-Host "  .\make.ps1 web            browser mode (CPA_WEB=1, http://localhost:8080)"
        Write-Host "  .\make.ps1 build          compile the Windows .exe (PyInstaller -> dist\)"
        Write-Host "  .\make.ps1 test           run the test suite"
        Write-Host "  .\make.ps1 fetch-rates    refresh json/interest_rates.json (Bank of Canada)"
        Write-Host "  .\make.ps1 fetch-vacancy  refresh the CMHC vacancy data"
        Write-Host "  .\make.ps1 clean          remove build\ dist\ *.spec"
    }
}
