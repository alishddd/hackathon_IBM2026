@echo off
cd /d "%~dp0"
set "THINKLENS_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%THINKLENS_PYTHON%" (
  "%THINKLENS_PYTHON%" server.py
  goto done
)
py -3 server.py
:done
pause
