@echo off
rem  Double-click this file to start HomingPigeon on Windows.
rem  The first time, it gets everything the app needs ready (a few minutes).
rem  After that it opens the app straight away.

setlocal
title HomingPigeon
cd /d "%~dp0"

call :find_python
if defined PY goto launch

echo.
echo   HomingPigeon needs Python, a free program from python.org.
echo   It is not installed on this computer yet.
echo.
where winget >nul 2>&1
if errorlevel 1 goto python_manual
choice /c YN /m "  Install Python now"
if errorlevel 2 goto python_manual
echo.
echo   Installing Python. This takes a minute or two...
echo.
winget install --id Python.Python.3.13 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
call :find_python
if defined PY goto launch

:python_manual
echo.
echo   Please install Python from the web page that is opening now.
echo   On the first screen of the installer, tick "Add python.exe to PATH".
echo   When it has finished, double-click this file again.
echo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:launch
%PY% "tools\launch.py"
if errorlevel 1 goto failed
exit /b 0

:failed
pause
exit /b 1


rem  ---------------------------------------------------------------------------
rem  Sets PY to a working Python 3.10+ command, or leaves it empty.
:find_python
set "PY="
call :try py -3
if not defined PY call :try python
if not defined PY call :try python3
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3
if not defined PY call :try "%LOCALAPPDATA%\Python\bin\python.exe"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do if not defined PY call :try "%%D\python.exe"
exit /b 0

rem  Uses the given command if it really runs Python 3.10 or newer. This also
rem  skips the "python" placeholder that only opens the Microsoft Store.
:try
%* -c "import sys; sys.exit(sys.hexversion < 0x030A0000)" >nul 2>&1
if errorlevel 1 exit /b 1
set PY=%*
exit /b 0
