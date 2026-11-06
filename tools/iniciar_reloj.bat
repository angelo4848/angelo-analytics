@echo off
title A. Analytics - Reloj de GitHub
cd /d "%~dp0"
python -m pip install --quiet --disable-pip-version-check --no-warn-script-location tzdata
python github_reloj.py
pause
