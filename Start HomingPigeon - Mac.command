#!/bin/bash
# Double-click this file to start HomingPigeon on a Mac.
# The first time, it gets everything the app needs ready (a few minutes).
# After that it opens the app straight away.

cd "$(dirname "$0")" || exit 1

PYTHON_INSTALLER="https://www.python.org/ftp/python/3.13.15/python-3.13.15-macos11.pkg"
PYTHON_PAGE="https://www.python.org/downloads/macos/"

# A usable Python is simply 3.10 or newer: the app draws with Qt, which pip
# installs complete with its own libraries, so nothing else has to be present.
python_ok() {
    "$1" -c 'import sys; sys.exit(sys.hexversion < 0x030A0000)' >/dev/null 2>&1
}

find_python() {
    PY=""
    local candidate
    # /usr/bin/python3 is skipped on purpose: on a Mac without developer tools it
    # pops up an install prompt, and Apple's copy is too old for the app anyway.
    for candidate in \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        "$(command -v python3 2>/dev/null)"; do
        [ -n "$candidate" ] && [ "$candidate" != "/usr/bin/python3" ] || continue
        if [ -x "$candidate" ] && python_ok "$candidate"; then
            PY="$candidate"
            return 0
        fi
    done
    return 1
}

pause_and_exit() {
    echo
    read -r -p "  Press Return to close this window." _
    exit 1
}

if ! find_python; then
    echo
    echo "  HomingPigeon needs Python, a free program from python.org."
    echo "  It is not installed on this Mac yet."
    echo
    read -r -p "  Download and open the Python installer now? [Y/n] " answer
    case "$answer" in
        [nN]*)
            open "$PYTHON_PAGE"
            echo "  Install Python from the page that just opened, then double-click this file again."
            pause_and_exit
            ;;
    esac

    installer="${TMPDIR:-/tmp}/homingpigeon-python.pkg"
    echo
    echo "  Downloading Python..."
    if curl -fL --progress-bar -o "$installer" "$PYTHON_INSTALLER"; then
        echo "  Follow the installer that opens (click Continue, then Install)."
        echo "  This window carries on by itself once the installer is closed."
        open -W "$installer"
        rm -f "$installer"
    else
        open "$PYTHON_PAGE"
        echo "  The download did not work. Install Python from the page that just opened,"
        echo "  then double-click this file again."
        pause_and_exit
    fi

    if ! find_python; then
        echo
        echo "  Python still could not be found. If the installer was cancelled,"
        echo "  double-click this file again to retry."
        pause_and_exit
    fi
fi

"$PY" tools/launch.py || pause_and_exit
echo "  HomingPigeon is opening. You can close this window."
