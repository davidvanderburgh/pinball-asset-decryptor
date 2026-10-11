r"""PAD-510 app-level proof: what the Emulate tab says after the game window closes on a
run whose game has gone quiet.

    python scripts/proof_pad510_app.py <git ref> <out dir> <tag>

<git ref> is exported to C:\tmp\PAD-510\app_<tag> (main for "before", the ticket
branch for "after") and served, with two TEST-ONLY patches so the run can stay
hidden and still have its sound player (the same two in both trees; neither touches
the teardown under test): watch.sh's "a hidden run is silent" rule is switched off,
and rigslot.muted() no longer mutes a hidden run.  The player is the real
padplay.py, muted by this app's own scratch audio_ctl.json ({"gain": 0.0, "muted":
true}); the driver stops the run at once if the player never says "volume -> 0.00".
The rig is one this script takes on the board (riglock.sh take --any) and releases,
in Ubuntu; the card is the Heisei 1.96a custom on C: (booted in place, no cache copy).

The app presses Start.  That card's game goes quiet in attract by itself (as
DragonRR's did): if it has not within 75 s, the guest is frozen (SIGSTOP, what a
pause does).  After the player has given up and been restarted four more times (his
log) the renderer is told to leave 13 s after the last restart (his timing), which
is the game window closing as far as watch.sh is concerned.  Then for 60 s, every
second: the tab's one button, its State and process count, the rig's own count, the
player's WSL stub, the Windows player, and whether the app's watch.sh wsl.exe is up.
Screenshots <tag>_03s / _08s / _20s.png are taken that many seconds after the close.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WORK = r"C:\tmp\PAD-510"
CARD = r"C:\tmp\heisei196a\orig_v196a.raw"
HELPER = "/mnt/c/tmp/PAD-510/slot1.sh"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui.tabs import emulate
emulate.EmulateTab._precache_kick = lambda self: None
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
#: run as ROOT in Ubuntu: <rig dir> take|release|count|deadfeed|close|ps|aud
HELPER_SH = r"""#!/bin/bash
R=$1
export HOME=/home/david
case "$2" in
take)
    out=$(bash "$R/riglock.sh" take --any PAD-510 "PAD-510 app-level close proof" 2>&1)
    echo "$out"
    printf '%s\n' "$out" | grep -o 'slot=[0-9]*' | head -1 | cut -d= -f2 > /mnt/c/tmp/PAD-510/slot
    exit 0 ;;
esac
SLOT=$(cat /mnt/c/tmp/PAD-510/slot 2>/dev/null)
case "$SLOT" in ''|0|*[!0-9]*) echo "no rig of our own (slot '$SLOT'): refusing" >&2; exit 2 ;; esac
export PAD_HOME=/home/david PAD_SLOT=$SLOT
. "$R/padpath.sh"
L=$PAD_LOGDIR/padaudio.log
case "$2" in
release)
    PAD_LABEL=PAD-510 bash "$R/killgame.sh" >/dev/null 2>&1
    # a root run leaves root-owned files in the rig; give them back
    find "$PAD_HOME/padslots/$SLOT/root/data" "$PAD_HOME/padslots/$SLOT/root/dump" \
        -user root -exec chown -h david:david {} + 2>/dev/null
    bash "$R/riglock.sh" release "$SLOT" PAD-510 ;;
count)
    a=$(grep -a '\[aud\] ---' "$PAD_LOGDIR/gzwatch.log" 2>/dev/null | tail -1 | sed -n 's/.*writei calls=\([0-9]*\).*/\1/p')
    echo "procs=$(bash "$R/alive.sh" --procs) stub=$(pad_count -f 'padplay\.py') restarts=$(grep -c 'restarting it' "$L" 2>/dev/null) muted=$(grep -c 'volume -> 0.00' "$L" 2>/dev/null) writei=${a:-?} game=$(pad_count -x game) host=$(pad_count -x padglhost) watch=$(pad_count -f '^bash .*watch\.sh')" ;;
deadfeed)
    for p in $(pad_pids -x game); do kill -STOP "$p" && echo "stopped game $p"; done ;;
close)
    pad_pkill -INT -x padglhost && echo "renderer told to leave" ;;
ps)
    ps -eo pid,etime,user,args | grep -E 'qemu|padglhost|watch\.sh|padrelay|padplay|playaudio' | grep -v grep | cut -c1-170 ;;
aud)
    tail -n "${3:-15}" "$L" ;;
esac
"""


def prepare(ref, tag):
    """Export <ref>, apply the two TEST-ONLY patches, write the rig helper."""
    tree = os.path.join(WORK, "app_" + tag)
    if os.path.isdir(tree):
        import shutil
        shutil.rmtree(tree)
    os.makedirs(tree)
    arc = subprocess.run(["git", "-C", REPO, "archive", ref], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", tree.replace("\\", "/")], input=arc.stdout, check=True)
    w = os.path.join(tree, "tools", "spike2_emu", "watch.sh")
    s = open(w, encoding="utf-8", newline="").read()
    old = 'if [ "$PAD_HIDDEN" = 1 ] && [ "$PAD_AUDIO" != 0 ]; then'
    assert s.count(old) == 1, "watch.sh: the hidden-run rule moved"
    open(w, "w", encoding="utf-8", newline="").write(s.replace(
        old, "if false; then  # PAD-510 TEST ONLY: a hidden run keeps its (muted) player"))
    r = os.path.join(tree, "pinball_decryptor", "core", "rigslot.py")
    s = open(r, encoding="utf-8", newline="").read()
    old = '    if hidden() or v == "0":'
    assert s.count(old) == 1, "rigslot.py: muted() moved"
    open(r, "w", encoding="utf-8", newline="").write(
        s.replace(old, '    if v == "0":  # PAD-510 TEST ONLY'))
    with open(os.path.join(WORK, "slot1.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write(HELPER_SH)
    return tree


def wsl_path(p):
    p = os.path.abspath(p)
    return "/mnt/%s%s" % (p[0].lower(), p[2:].replace("\\", "/"))


def helper(rig, *args, timeout=60):
    r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "-e", "bash", HELPER, rig]
                       + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return ((r.stdout or "") + (r.stderr or "")).strip()


def counts(rig):
    out = {}
    for kv in helper(rig, "count").split():
        k, _, v = kv.partition("=")
        out[k] = v
    return out


def watch_wsl_alive(tree):
    """The app's own watch.sh launch: a wsl.exe whose command line names it."""
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "@(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'wsl.exe' -and "
         "$_.CommandLine -like '*watch.sh*' -and $_.CommandLine -like '*%s*' }).Count"
         % wsl_path(tree)], capture_output=True, text=True, timeout=60)
    return (r.stdout or "").strip()


def windows_players(slot):
    """The Windows padplay.py processes on this rig's port (45997 + slot)."""
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "@(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'py*' -and "
         "$_.CommandLine -like '*padplay.py*' -and $_.CommandLine -like '* %d *' }).Count"
         % (45997 + int(slot))], capture_output=True, text=True, timeout=60)
    return (r.stdout or "").strip()


def main():
    ref, out, tag = sys.argv[1], os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out, exist_ok=True)
    tree = prepare(ref, tag)
    rig = wsl_path(os.path.join(tree, "tools", "spike2_emu"))
    print(helper(rig, "take"), flush=True)
    slot = open(os.path.join(WORK, "slot"), encoding="utf-8").read().strip()
    assert slot and slot != "0", "no rig of our own"
    log = open(os.path.join(out, tag + ".log"), "w", encoding="utf-8")

    def say(*a):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), " ".join(str(x) for x in a))
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    scratch = tempfile.mkdtemp(prefix="pad510app-")
    launcher = os.path.join(scratch, "launch510.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % tree)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": CARD}, f)
    cfgdir = os.path.join(scratch, "cfg", "pinball_decryptor")
    os.makedirs(cfgdir, exist_ok=True)
    with open(os.path.join(cfgdir, "audio_ctl.json"), "w", encoding="utf-8") as f:
        json.dump({"gain": 0.0, "muted": True}, f)
    tmp = os.path.join(scratch, "tmp")
    os.makedirs(tmp, exist_ok=True)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "TEMP": tmp, "TMP": tmp,
           "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "1", "PAD_RUNTIME": "0",
           "PAD_SLOT": slot, "PAD_TICKET": "", "PAD_LABEL": "PAD-510-check",
           "PAD_HIDDEN": "1", "PAD_AUDIO": "1",
           "PAD_CARD_CACHE": "0", "WSLENV": "PAD_CARD_CACHE"}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env,
                                        app_cmd=[sys.executable, launcher])
    say("tree", tree, "| rig", slot, "| server", url.split("?")[0], "| scratch", scratch)

    def tab():
        st = webui_shot.state(url).get("emulate", {})
        vals = st.get("vals", {})
        return ((st.get("run_btn") or {}).get("label"), vals.get("state"), vals.get("procs"))

    shots = {}
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1250})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            t0 = time.time()
            while time.time() - t0 < 90 and not webui_shot.state(url).get(
                    "emulate", {}).get("vals", {}).get("procs"):
                time.sleep(1)
            say("idle:", tab(), "| rig:", counts(rig))
            say("rig before:", helper(rig, "ps") or "(nothing running)")

            webui_shot.api(url, "emulate.toggle")
            say("Start pressed")
            t0, last = time.time(), None
            while time.time() - t0 < 300:
                now = tab()
                if now != last:
                    say("  %4ds %s" % (time.time() - t0, now))
                    last = now
                if now[1] == "Game running":            # status.sh's attract/running
                    break
                time.sleep(2)
            c = counts(rig)
            say("game up:", tab(), "| rig:", c)
            if c.get("muted", "0") == "0":
                say("NO MUTE LINE FROM THE PLAYER: stopping now")
                webui_shot.api(url, "emulate.toggle")
                time.sleep(20)
                return

            # the feed goes dead: by itself, or frozen as a pause freezes it
            t1, w0 = time.time(), c.get("writei")
            while time.time() - t1 < 75:
                time.sleep(5)
                c = counts(rig)
                if c.get("restarts", "0") != "0":
                    say("the game went quiet by itself:", c)
                    break
            else:
                say("still writing sound after 75 s (writei %s -> %s); freezing the game:"
                    % (w0, c.get("writei")), helper(rig, "deadfeed"))
            base = int(c.get("restarts", "0") or 0)
            t1, last_r, last_t = time.time(), base, time.time()
            while time.time() - t1 < 400:
                c = counts(rig)
                r = int(c.get("restarts", "0") or 0)
                if r != last_r:
                    say("  player restart %d" % r, c)
                    last_r, last_t = r, time.time()
                if r - base >= 4:
                    break
                time.sleep(2)
            while time.time() - last_t < 13:
                time.sleep(0.5)
            say("before the close:", tab(), "| rig:", counts(rig))

            helper(rig, "close")
            tc = time.time()
            say("WINDOW CLOSED (renderer told to leave)")
            alive = {"v": "?"}

            winp = {"v": "?"}

            def poll_wsl():
                while time.time() - tc < 62:
                    alive["v"] = watch_wsl_alive(tree)
                    winp["v"] = windows_players(slot)
                    time.sleep(1)
            threading.Thread(target=poll_wsl, daemon=True).start()
            rig_c = {"v": {}}

            def poll_rig():
                while time.time() - tc < 62:
                    rig_c["v"] = counts(rig)
                    time.sleep(1)
            threading.Thread(target=poll_rig, daemon=True).start()
            first_start = None
            while time.time() - tc < 60:
                dt = time.time() - tc
                now = tab()
                c = rig_c["v"]
                say("  +%4.1f s  button %-16r state %-22r %-26r | watch wsl.exe %s | rig procs %s"
                    " stub %s | Windows player %s"
                    % (dt, now[0], now[1], now[2], alive["v"], c.get("procs"), c.get("stub"),
                       winp["v"]))
                if first_start is None and now[0] == "Start emulator":
                    first_start = dt
                for at in (3, 8, 20):
                    if at not in shots and dt >= at:
                        path = os.path.join(out, "%s_%02ds.png" % (tag, at))
                        page.screenshot(path=path)
                        shots[at] = path
                time.sleep(1)
            say("RESULT %s: Start emulator came back %s after the close"
                % (tag, ("%.1f s" % first_start) if first_start is not None else "NOT within 60 s"))
            if tab()[0] == "Stop emulator":
                say("pressing Stop to end it")
                webui_shot.api(url, "emulate.toggle")
                time.sleep(25)
                say("after Stop:", tab(), "| rig:", counts(rig))
            browser.close()
    finally:
        proc.kill()
        say("rig after:", helper(rig, "ps") or "(nothing running)")
        say("released:", helper(rig, "release"))
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'wsl.exe'"
             " -and $_.CommandLine -like '*%s*' -and $_.CommandLine -notlike '*watch.sh*' }"
             " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % wsl_path(tree)],
            capture_output=True, timeout=60)


if __name__ == "__main__":
    main()
