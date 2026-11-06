@echo off
rem Hace que "iniciar_sofa_sync.bat" arranque solo cada vez que enciendes el PC (minimizado).
set "DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\A_Analytics_SofaSync.bat"
(
  echo @echo off
  echo cd /d "%~dp0"
  echo start "A. Analytics SofaSync" /min cmd /c "%~dp0iniciar_sofa_sync.bat"
) > "%DEST%"
echo.
echo Listo. A partir de ahora el programa de SofaScore arranca solo al encender el PC.
echo Para quitarlo: borra "%DEST%"
echo.
start "" /min cmd /c "%~dp0iniciar_sofa_sync.bat"
pause
