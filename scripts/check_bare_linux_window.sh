#!/bin/bash
# The window from pip on a bare Ubuntu, run inside an ubuntu:NN.04 container
# by .github/workflows/window.yml. The checkout is mounted at /src, an X
# server on the runner is reachable as $DISPLAY, and frames go to /out.
#
# Proves, with nothing installed but Python and what this script adds:
#   1. Every library but libxcb-icccm4 and libxcb-keysyms1, the state of the
#      WSL machine this was reported from: `shambles gui --new` explains
#      and exits 1 instead of aborting (134), and names the two libraries,
#      and plain `shambles gui` heads for the classic window.
#   2. The list in shambles/app/window_check.py: ldd finds everything Qt's
#      X11 plugin and every Qt file the window loads link against.
#   3. With only that list, the window opens and draws, on the software
#      renderer (what WSL uses) and on OpenGL.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
quiet() { "$@" >/tmp/step.log 2>&1 || { cat /tmp/step.log; return 1; }; }
step() { printf '\n== %s\n' "$*"; }

step "Python only"
quiet apt-get update
quiet apt-get install -y --no-install-recommends python3 python3-venv
. /etc/os-release && echo "$PRETTY_NAME, $(python3 --version)"

# pip writes build files into the source tree, and /src is read-only.
cp -r /src /tmp/src
quiet python3 -m venv /tmp/v
quiet /tmp/v/bin/pip install "/tmp/src[gui]"
py=/tmp/v/bin/python
packages=$($py -c 'from shambles.app.window_check import APT_PACKAGES as p; print(" ".join(p))')
pyside=$($py -c 'import os, PySide6; print(os.path.dirname(PySide6.__file__))')
$py -c 'import PySide6; print("PySide6", PySide6.__version__)'
home=$(mktemp -d)

step "1. All but libxcb-icccm4 and libxcb-keysyms1"
partial=$(printf '%s\n' $packages | grep -vx -e libxcb-icccm4 -e libxcb-keysyms1)
quiet apt-get install -y --no-install-recommends $partial
status=0
/tmp/v/bin/shambles gui --new --home "$home" 2>/tmp/new.txt || status=$?
cat /tmp/new.txt
echo "exit status $status"
test "$status" = 1
grep -q "libxcb-icccm.so.4" /tmp/new.txt
grep -q "libxcb-keysyms.so.1" /tmp/new.txt
grep -q "sudo apt install" /tmp/new.txt

# No python3-tk in this container, so the classic window cannot open
# either; what matters is that the new one is given up on with a reason.
status=0
/tmp/v/bin/shambles gui --home "$home" 2>/tmp/gui.txt || status=$?
cat /tmp/gui.txt
echo "exit status $status"
test "$status" = 1
grep -q "could not start here" /tmp/gui.txt
grep -q "libxcb-keysyms.so.1" /tmp/gui.txt

step "2. The full list"
quiet apt-get install -y --no-install-recommends $packages
loaded=(
    "$pyside"/Qt{Core,Gui,Network,OpenGL,Qml,Quick}.abi3.so
    "$pyside"/Qt/plugins/platforms/libqxcb.so
    "$pyside"/Qt/plugins/xcbglintegrations/*.so
    "$pyside"/Qt/plugins/platforminputcontexts/libcomposeplatforminputcontextplugin.so
    "$pyside"/Qt/qml/QtQuick/Controls/Basic/libqtquickcontrols2basicstyleplugin.so
    "$pyside"/Qt/qml/QtQuick/Layouts/libqquicklayoutsplugin.so
    "$pyside"/Qt/qml/QtQuick/Templates/libqtquicktemplates2plugin.so
)
missing=$(for f in "${loaded[@]}"; do test -f "$f" || echo "no such file $f"; ldd "$f" | grep "not found" || true; done | sort -u)
if [ -n "$missing" ]; then
    echo "Missing after installing the list:"
    echo "$missing"
    exit 1
fi
echo "ldd finds every library for ${#loaded[@]} files."

step "3. The window draws"
tag=$(. /etc/os-release && echo "$VERSION_ID")
for render in software gpu; do
    status=0
    SHAMBLES_RENDER=$render SHAMBLES_WINDOW_SMOKE=/out/bare-$tag-$render.png \
        /tmp/v/bin/shambles gui --new --home "$home" || status=$?
    cat "/out/bare-$tag-$render.png.log" || true
    test "$status" = 0
    test -s "/out/bare-$tag-$render.png"
done
