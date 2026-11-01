@echo off
title Bot A. Analytics (PC)
cd /d "%~dp0"
python -m pip install --quiet --disable-pip-version-check curl_cffi
python pc_bot.py
pause
