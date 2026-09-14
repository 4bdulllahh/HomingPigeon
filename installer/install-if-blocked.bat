@echo off
rem  Backup installer for PCs where Windows blocks "HomingPigeon Setup.exe".
rem
rem  Windows 11's Smart App Control blocks new programs that aren't digitally
rem  signed. This file avoids that: it uses only tools built into Windows to
rem  download Python from python.org (which IS signed), checks the download is
rem  genuine, and then opens the normal HomingPigeon Setup window with it.
rem
rem  The values in @...@ are filled in by tools/build_installer.py.

setlocal
title Install HomingPigeon
cd /d "%~dp0"

set "PY_VERSION=@PYTHON_VERSION@"
set "ARCH=amd64"
set "SHA=@SHA_AMD64@"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" goto arm
if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" goto arm
goto arch_done
:arm
set "ARCH=arm64"
set "SHA=@SHA_ARM64@"
:arch_done

set "TARGET=%LOCALAPPDATA%\Programs\HomingPigeon"
if not "%~1"=="" set "TARGET=%~1"
set "PYDIR=%TARGET%\python"
set "ZIP=%TEMP%\HomingPigeon-python-%PY_VERSION%-%ARCH%.zip"
set "URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-%ARCH%.zip"

echo.
echo   HomingPigeon - backup installer
echo   ===============================
echo.

if not exist "files\installer\setup_app.py" goto not_extracted

rem  Python already there and the right version? Go straight to Setup.
if not exist "%PYDIR%\pythonw.exe" goto get_python
if not exist "%PYDIR%\homingpigeon-python.txt" goto get_python
set /p HAVE=<"%PYDIR%\homingpigeon-python.txt"
if "%HAVE%"=="%PY_VERSION%" goto run_setup

:get_python
echo   Step 1 of 3: Downloading Python %PY_VERSION% from python.org (about 34 MB)
echo   %URL%
echo.
curl.exe --fail --location --progress-bar --output "%ZIP%" "%URL%"
if errorlevel 1 goto download_failed

echo.
echo   Step 2 of 3: Checking the download is genuine
certutil -hashfile "%ZIP%" SHA256 | find /i "%SHA%" >nul
if errorlevel 1 goto bad_hash
echo   OK - it matches the official python.org release.
echo.

echo   Step 3 of 3: Unpacking Python into %PYDIR%
if exist "%PYDIR%.new" rmdir /s /q "%PYDIR%.new"
mkdir "%PYDIR%.new"
tar -xf "%ZIP%" -C "%PYDIR%.new"
if errorlevel 1 goto unpack_failed
if exist "%PYDIR%" rmdir /s /q "%PYDIR%"
move "%PYDIR%.new" "%PYDIR%" >nul
if errorlevel 1 goto unpack_failed
>"%PYDIR%\homingpigeon-python.txt" echo %PY_VERSION%
del "%ZIP%" >nul 2>&1
echo   Done.
echo.

:run_setup
echo   Opening HomingPigeon Setup...
rem  (no parenthesised blocks here: a folder name containing brackets would break them)
if not "%~1"=="" goto run_setup_custom
start "" "%PYDIR%\pythonw.exe" -E -s "files\installer\setup_app.py"
exit /b 0
:run_setup_custom
start "" "%PYDIR%\pythonw.exe" -E -s "files\installer\setup_app.py" --target "%TARGET%"
exit /b 0

:not_extracted
echo   The HomingPigeon files are missing next to this file.
echo   Please unzip the download first: right-click the .zip file, choose
echo   "Extract All...", then double-click this file inside the new folder.
goto fail

:download_failed
echo.
echo   The download didn't work. Check your internet connection and try again.
goto fail

:bad_hash
del "%ZIP%" >nul 2>&1
echo   The download didn't match the official python.org file, so it was deleted.
echo   This is usually a broken download. Please try again.
goto fail

:unpack_failed
echo   Python couldn't be unpacked. Make sure HomingPigeon is closed and try again.
goto fail

:fail
echo.
pause
exit /b 1
