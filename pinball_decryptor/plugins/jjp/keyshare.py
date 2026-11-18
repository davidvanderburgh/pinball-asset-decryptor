"""A key sharing stick: a JJP machine lends its security key to PAD (PAD-1416).

The machine side is ``tools/jjp_emu/padkeyshare.py``, a small USB/IP server.
This writes the USB stick that puts it on a machine, through the same hot fix
a mode stick uses (service menu, Update USB screen, Plus Minus Plus Minus,
ENTER twice: the game runs ``hotfix/runme.sh`` as root and reboots).  No
reinstall: scores, audits and settings in /jjpe/perm are not touched.

On the machine the server is started once per boot from ``rungame.sh`` (one
hook line after ``runonce.sh``, beside the modes' own) as its own systemd
unit, so the game restarting never stops it.  PAD's Emulate tab then takes the
key with "On another PC (network)" and the machine's address.  While PAD has
it, the game shows its own "SECURITY KEY MISSING" screen and rescans; when PAD
lets go the game starts again by itself.  A Sentinel HL Pro key is local
only, so the machine and a PC can never use it at the same time.

The stick runs on every JJP title: it checks for python3 and the kernel's
usbip-host driver first and changes nothing if either is missing.
"""

import hashlib
import os
import shutil
import time

from . import custom_modes as CM

ACTIONS = ("install", "remove")
STICK_DIR = "hotfix"
MARK = "PAD key sharing stick"
LOG = "padkeyshare_install.log"
HOOK_MARK = "# PAD key sharing:"
HOOK_LINES = [
    "",
    HOOK_MARK + " lends the security key to PAD on this network (padkeyshare.sh)",
    "[ -r $JJPEDIR/scripts/padkeyshare.sh ] && . $JJPEDIR/scripts/padkeyshare.sh",
]
RUNONCE_LINE = "$JJPEDIR/scripts/runonce.sh"
SERVER_LOG = "/jjpe/temp/padkeyshare.log"

PADKEYSHARE_SH = """#!/bin/sh
# PAD key sharing (PAD-1416).  Sourced by rungame.sh once per boot: starts the
# key server as its own systemd unit, so the game restarting never stops it.
if [ -r $JJPEDIR/padkeyshare/padkeyshare.py ]; then
    if command -v systemd-run >/dev/null 2>&1; then
        systemd-run --unit=padkeyshare --quiet /usr/bin/python3 \\
            $JJPEDIR/padkeyshare/padkeyshare.py --log %(log)s >/dev/null 2>&1 \\
            && echo "PAD key sharing: the security key is offered to PAD on port 3240"
    elif ! pgrep -f padkeyshare/padkeyshare.py >/dev/null 2>&1; then
        setsid /usr/bin/python3 $JJPEDIR/padkeyshare/padkeyshare.py \\
            --log %(log)s </dev/null >/dev/null 2>&1 &
        echo "PAD key sharing: the security key is offered to PAD on port 3240"
    fi
fi
""" % {"log": SERVER_LOG}

RUNME_SH = r"""#!/bin/dash
# @MARK@ (PAD-1416), written @WRITTEN@.
# Run by the game's own scripts/hotfix.sh from the service menu's Update USB
# screen (Plus, Minus, Plus, Minus, then ENTER twice); the game reboots after.
# Scores and settings in /jjpe/perm are never touched.
ACTION=@ACTION@
SRC=$(dirname "$0")
STICK=$(dirname "$SRC")
J=${JJPEDIR:-/jjpe/gen1}
LOG=${PAD_STICK_LOG:-/jjpe/temp/@LOG@}
MARK='@HOOKMARK@'
ANCHOR='@ANCHOR@'
say() {
    echo "$(date '+%F %T') $*" >> "$LOG"
    echo "$(date '+%F %T') $*" >> "$STICK/@LOG@" 2>/dev/null
}
fail() { say "FAILED: $*"; exit 1; }
say "PAD key sharing stick: $ACTION on $J"
unhook() {
    awk -v m="$MARK" '
        index($0, m) == 1 { h = 0; s = 1; next }
        s { s = 0; next }
        { if (h) print ""; h = 0 }
        $0 == "" { h = 1; next }
        { print }
        END { if (h) print "" }' "$J/scripts/rungame.sh" > "$J/scripts/rungame.sh.pad" || return 1
    cat "$J/scripts/rungame.sh.pad" > "$J/scripts/rungame.sh" && rm -f "$J/scripts/rungame.sh.pad"
}
case "$ACTION" in
remove)
    systemctl stop padkeyshare 2>/dev/null
    if grep -q "^$MARK" "$J/scripts/rungame.sh"; then unhook || fail "could not edit rungame.sh"; fi
    rm -rf "$J/padkeyshare" "$J/scripts/padkeyshare.sh"
    sync; say "key sharing REMOVED: rungame.sh without its line, the key stays in the machine"
    ;;
install)
    [ -r "$SRC/padkeyshare/padkeyshare.py" ] || fail "no padkeyshare/padkeyshare.py on the stick"
    ( cd "$SRC" && sha256sum -c --quiet padkeyshare.sha256 ) >> "$LOG" 2>&1 \
        || fail "a file on the stick does not match what was written (copy it again)"
    PY=${PAD_STICK_PYTHON:-/usr/bin/python3}             # the two overrides are for tests only
    KMODS=${PAD_STICK_KMODS:-/lib/modules/$(uname -r)}
    [ -x "$PY" ] || fail "this machine has no $PY - nothing changed"
    if ! find "$KMODS" -name 'usbip-host.ko*' 2>/dev/null | grep -q . \
            && ! grep -q 'usbip-host' "$KMODS/modules.builtin" 2>/dev/null; then
        fail "this machine's system ($KMODS) has no usbip-host driver - nothing changed"
    fi
    if ! grep -q "^$MARK" "$J/scripts/rungame.sh"; then
        n=$(awk -v a="$ANCHOR" '{ t = $0; gsub(/^[ \t]+|[ \t]+$/, "", t) } t == a { n++ } END { print n + 0 }' "$J/scripts/rungame.sh")
        [ "$n" = 1 ] || fail "rungame.sh has $n '$ANCHOR' lines, not 1 - not edited, nothing changed"
    fi
    mkdir -p "$J/padkeyshare" && cp "$SRC/padkeyshare/padkeyshare.py" "$J/padkeyshare/padkeyshare.py" \
        && chmod 0644 "$J/padkeyshare/padkeyshare.py" || fail "could not copy the key server"
    cp "$SRC/padkeyshare.sh" "$J/scripts/padkeyshare.sh" && chmod 0755 "$J/scripts/padkeyshare.sh" \
        || fail "could not write scripts/padkeyshare.sh"
    if ! grep -q "^$MARK" "$J/scripts/rungame.sh"; then
        awk -v a="$ANCHOR" -v m='@HOOK1@' -v g='@HOOK2@' '
            { print; t = $0; gsub(/^[ \t]+|[ \t]+$/, "", t) }
            t == a { print ""; print m; print g }' "$J/scripts/rungame.sh" > "$J/scripts/rungame.sh.pad" \
            && cat "$J/scripts/rungame.sh.pad" > "$J/scripts/rungame.sh" && rm -f "$J/scripts/rungame.sh.pad" \
            || fail "could not hook rungame.sh"
    fi
    sync
    say "INSTALLED: after the reboot the machine offers its security key to PAD on port 3240"
    ;;
*)
    fail "unknown action $ACTION"
    ;;
esac
exit 0
"""

README = """PAD key sharing stick: %(what)s
Written %(written)s by PAD.

1. Copy the folder "hotfix" (and this file) to the top of a USB stick (FAT32).
2. Machine on, coin door open: open the service menu and go to its USB update
   screen (Software Update > USB Update), stick in. It says "No update data
   was found"; that is expected.
3. Hold the LEFT FLIPPER button and, still holding it, press
   Plus, Minus, Plus, Minus. It asks "Press ENTER to apply HOTFIX".
   Press ENTER, then ENTER again.
4. The game reboots. Take the stick out. What happened is written to
   %(log)s on the stick (and /jjpe/temp/%(log)s on the machine).

%(after)s
Scores, audits and settings are not touched.
"""

AFTER = {
    "install": (
        "From then on the machine offers its security key to PAD on the same\n"
        "network. In PAD's Emulate tab pick \"On another PC (network)\" and type\n"
        "the machine's IP address (leave Bus ID empty). While PAD uses the key\n"
        "the machine shows SECURITY KEY MISSING; when PAD stops, the game\n"
        "starts again by itself. Only one of them can use the key at a time.\n"),
    "remove": "The machine stops offering its key; the game is as it was.\n",
}


def server_source():
    """padkeyshare.py's text, from the tools the app ships."""
    with open(os.path.join(CM.tools_dir(), "padkeyshare.py"), "rb") as f:
        return f.read()


def hotfix_owner(stick):
    """"" no hot fix, "pad" one of PAD's (a modes or key sharing stick,
    replaced freely), "other" someone else's (never overwritten)."""
    return CM.hotfix_on(stick)


def write_stick(out, action="install"):
    """Write the stick folder at *out*.  -> (ok, lines)."""
    if action not in ACTIONS:
        return False, ["refused: unknown action %r" % action]
    out = os.path.abspath(out)
    if not os.path.isdir(out):
        return False, ["refused: %s is not a folder" % out]
    if hotfix_owner(out) == "other":
        return False, ["refused: %s already has a hot fix that is not PAD's - use another stick, "
                       "or delete its hotfix folder first" % out]
    written = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    hot = os.path.join(out, STICK_DIR)
    if os.path.exists(hot):
        shutil.rmtree(hot)
    os.makedirs(hot)

    def write(rel, data):
        p = os.path.join(hot, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    if action == "install":
        src = server_source()
        write("padkeyshare/padkeyshare.py", src)
        write("padkeyshare.sh", PADKEYSHARE_SH)
        write("padkeyshare.sha256", "%s  padkeyshare/padkeyshare.py\n" % hashlib.sha256(src).hexdigest())
    runme = RUNME_SH
    for k, v in (("@MARK@", MARK), ("@WRITTEN@", written), ("@ACTION@", action), ("@LOG@", LOG),
                 ("@HOOKMARK@", HOOK_MARK), ("@ANCHOR@", RUNONCE_LINE),
                 ("@HOOK1@", HOOK_LINES[1]), ("@HOOK2@", HOOK_LINES[2])):
        runme = runme.replace(k, v)
    write("runme.sh", runme)
    what = {"install": "the machine lends its security key to PAD",
            "remove": "take key sharing out again"}[action]
    with open(os.path.join(out, "PADKEYSHARE_README.txt"), "wb") as f:
        f.write((README % {"what": what, "written": written, "log": LOG, "after": AFTER[action]})
                .replace("\n", "\r\n").encode())
    return True, ["wrote %s: %s" % (hot, what)]
