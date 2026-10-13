#!/bin/sh
# Register the OpenGirGit launcher entry (and icon) for the current user.
#
# Start OpenGirGit from your application grid afterwards: on Wayland the
# GlobalShortcuts portal only grants global hotkeys to processes that the
# desktop launched from an installed entry (it derives the app id from the
# systemd scope + this .desktop file).  A plain terminal launch keeps the
# window-local fallback shortcuts.
#
# Usage:
#   ./install-linux.sh [path-to-OpenGirGit]     # default: ./OpenGirGit next to this script
#   ./install-linux.sh --uninstall

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exe=$here/OpenGirGit
uninstall=0
for arg in "$@"; do
    case $arg in
        --uninstall) uninstall=1 ;;
        *) exe=$arg ;;
    esac
done

data=${XDG_DATA_HOME:-$HOME/.local/share}
apps=$data/applications
icons=$data/icons/hicolor/scalable/apps
entry=$apps/org.opengirgit.OpenGirGit.desktop

refresh() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$apps" >/dev/null 2>&1 || true
    fi
}

if [ "$uninstall" = 1 ]; then
    rm -f "$entry" "$icons/org.opengirgit.OpenGirGit.svg"
    refresh
    echo "removed $entry"
    exit 0
fi

if [ ! -x "$exe" ]; then
    echo "error: $exe is not executable" >&2
    echo "usage: $0 [path-to-OpenGirGit] [--uninstall]" >&2
    exit 1
fi

mkdir -p "$apps" "$icons"
sed "s|^Exec=.*|Exec=$exe|" "$here/org.opengirgit.OpenGirGit.desktop" > "$entry"
cp "$here/org.opengirgit.OpenGirGit.svg" "$icons/org.opengirgit.OpenGirGit.svg"
refresh

echo "installed $entry"
echo "  Exec=$exe"
echo
echo "Start OpenGirGit from your application grid so the desktop can grant it"
echo "global shortcuts (Wayland); global hotkeys are disabled in terminal launches."
