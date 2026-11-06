@echo off
title A. Analytics - SofaScore a GitHub
cd /d "%~dp0"
python -m pip install --quiet --disable-pip-version-check --no-warn-script-location truststore certifi tzdata
python -m pip install --quiet --disable-pip-version-check --no-warn-script-location --only-binary=:all: curl_cffi
python sofa_sync.py
pause
