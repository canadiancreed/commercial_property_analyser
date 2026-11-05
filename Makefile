# Commercial Property Analyser - dev task runner (Git Bash / Unix shells).
#
# Windows PowerShell users without `make`: use  .\make.ps1 <target>  instead
# (same targets, zero install). To use this Makefile, install make once:
#   winget install GnuWin32.Make      (or:  choco install make)
# then run it from Git Bash.
#
# Override the interpreter if `python` is not on PATH:  make build PY=py
PY ?= python

.PHONY: help run web build compile test fetch-rates fetch-vacancy clean

help:
	@echo "Targets:"
	@echo "  make run            launch the desktop app (native window)"
	@echo "  make web            launch in the browser (CPA_WEB=1, http://localhost:8080)"
	@echo "  make build          compile the Windows .exe (PyInstaller onefile -> dist/)"
	@echo "  make test           run the test suite"
	@echo "  make fetch-rates    refresh json/interest_rates.json from the Bank of Canada"
	@echo "  make fetch-vacancy  refresh the CMHC vacancy data"
	@echo "  make clean          remove build/ dist/ *.spec"

run:
	$(PY) poc_nicegui/app.py

web:
	CPA_WEB=1 $(PY) poc_nicegui/app.py

build compile:
	$(PY) poc_nicegui/build.py

test:
	$(PY) -m pytest -q

fetch-rates:
	$(PY) scripts/fetch_interest_rates.py

fetch-vacancy:
	$(PY) scripts/fetch_geographic_crosswalk.py
	$(PY) scripts/fetch_vacancy_rates.py

clean:
	rm -rf build dist *.spec
