@echo off
title Bot A. Analytics (PC)
cd /d "%~dp0"
python -m pip install --quiet --disable-pip-version-check --no-warn-script-location truststore certifi pillow
python -m pip install --quiet --disable-pip-version-check --no-warn-script-location --only-binary=:all: curl_cffi
python pc_bot.py
pause
