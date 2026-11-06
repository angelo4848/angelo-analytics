@echo off
rem Hace que el reloj de GitHub arranque solo cada vez que se enciende el VPS (minimizado).
set "DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\A_Analytics_Reloj.bat"
(
  echo @echo off
  echo start "A. Analytics Reloj" /min cmd /c "%~dp0iniciar_reloj.bat"
) > "%DEST%"
echo.
echo Listo. El reloj de GitHub arranca solo cada vez que se enciende este ordenador.
echo Para quitarlo: borra "%DEST%"
echo.
start "" /min cmd /c "%~dp0iniciar_reloj.bat"
pause
