#!/bin/bash
# Start HomingPigeon on Linux: double-click this file (choose "Run" or
# "Run in Terminal" if asked), or run it from a terminal.
# The first time, it gets everything the app needs ready (a few minutes).

cd "$(dirname "$0")" || exit 1

# Started from a file manager with no terminal: reopen in one so progress and
# any problems are visible.
if [ ! -t 1 ] && [ -z "$HOMINGPIGEON_IN_TERMINAL" ]; then
    export HOMINGPIGEON_IN_TERMINAL=1
    script="$(pwd)/$(basename "$0")"
    if command -v gnome-terminal >/dev/null 2>&1; then exec gnome-terminal -- "$script"; fi
    if command -v konsole >/dev/null 2>&1; then exec konsole -e "$script"; fi
    if command -v xfce4-terminal >/dev/null 2>&1; then exec xfce4-terminal -x "$script"; fi
    if command -v mate-terminal >/dev/null 2>&1; then exec mate-terminal -x "$script"; fi
    if command -v xterm >/dev/null 2>&1; then exec xterm -e "$script"; fi
fi

pause_and_exit() {
    echo
    read -r -p "  Press Enter to close this window." _
    exit 1
}

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(sys.hexversion < 0x030A0000)' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo
    echo "  HomingPigeon needs Python 3.10 or newer. Install it, then run this file again:"
    echo "    Ubuntu / Debian / Mint:  sudo apt install python3 python3-venv libxcb-cursor0"
    echo "    Fedora:                  sudo dnf install python3 xcb-util-cursor"
    echo "    Arch:                    sudo pacman -S python xcb-util-cursor"
    pause_and_exit
fi

"$PY" tools/launch.py || pause_and_exit
