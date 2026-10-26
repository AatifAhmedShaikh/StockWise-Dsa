@echo off
rem One-click start for Windows. Nothing to install: only Python 3.8 or newer is needed.
rem The C library ships pre-built, and the web interface uses only Python's standard library.
cd /d "%~dp0"

set PY=python
where python >nul 2>nul
if errorlevel 1 set PY=py
where %PY% >nul 2>nul
if errorlevel 1 goto nopython

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

%PY% stockwise.py
if errorlevel 1 pause
exit /b 0

:nopython
echo Python 3.8 or newer was not found.
echo Install it from python.org and tick "Add python.exe to PATH", then run this file again.
pause
exit /b 1
