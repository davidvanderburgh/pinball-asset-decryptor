r"""PAD-738 proof: Restart game keeps the virtual playfield open.

    python scripts/proof_pad738_restart.py <git ref> <out dir> <tag>

<git ref> is exported to %TEMP%\PAD-738\app_<tag> (main for "before", the ticket
branch for "after") and served as the real app, hidden and muted, on a rig this
script takes under its own label (riglock.sh take --any PAD-738) and gives back,
in Ubuntu (PAD_RUNTIME=0). The card is stock godzilla_pro 1.16.

The app presses Start and waits for "Game running". Then the export's own
virtual playfield (playfield.py, the page the window shows) is run against that
rig with no window - PAD_PF_WINDOW=browser and the URL handed to a headless Edge
instead of a browser tab - and handed the app's volume file, as the app hands it,
so its bottom bar carries Restart game. The script clicks THAT button, and then
every 2 s logs: is the playfield process still there, the app's button and
State, and the rig's game / renderer / watch.sh pids. It photographs the game's
own framebuffer (glshot.sh) as it goes, and at the end the playfield page:
<tag>_playfield.png, beside <tag>_game_*.png. Then Stop, and the rig goes back.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WORK = r"C:\Users\david\AppData\Local\Temp\PAD-738"
CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
HELPER = "/mnt/c/Users/david/AppData/Local/Temp/PAD-738/rig.sh"
LABEL = "PAD-738"
GAME = "godzilla_pro"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui.tabs import emulate
emulate.EmulateTab._precache_kick = lambda self: None
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
#: the playfield with its browser rung's URL written to a file, not opened
PF_LAUNCHER = r'''
import runpy, sys, webbrowser
out = sys.argv.pop(1)
def _open(url, *a, **k):
    with open(out, "a", encoding="utf-8") as f:
        f.write(url + "\n")
    return True
webbrowser.open = _open
sys.argv[0] = sys.argv[1]
del sys.argv[1]
runpy.run_path(sys.argv[0], run_name="__main__")
'''
#: run as root in Ubuntu: <rig dir> take|release|count|shot <png>
HELPER_SH = r"""#!/bin/bash
R=$1
export HOME=/home/david
case "$2" in
take)
    out=$(sudo -u david -H bash "$R/riglock.sh" take --any PAD-738 "PAD-738 Restart game proof" 2>&1)
    echo "$out"
    printf '%s\n' "$out" | grep -o 'slot=[0-9]*' | head -1 | cut -d= -f2 > /mnt/c/Users/david/AppData/Local/Temp/PAD-738/slot
    exit 0 ;;
esac
SLOT=$(cat /mnt/c/Users/david/AppData/Local/Temp/PAD-738/slot 2>/dev/null)
case "$SLOT" in ''|0|*[!0-9]*) echo "no rig of our own (slot '$SLOT'): refusing" >&2; exit 2 ;; esac
export PAD_HOME=/home/david PAD_SLOT=$SLOT PAD_LABEL=PAD-738
. "$R/padpath.sh"
case "$2" in
release)
    bash "$R/killgame.sh" >/dev/null 2>&1
    find "$PAD_HOME/padslots/$SLOT/root/data" "$PAD_HOME/padslots/$SLOT/root/dump" \
        -user root -exec chown -h david:david {} + 2>/dev/null
    sudo -u david -H bash "$R/riglock.sh" release "$SLOT" PAD-738 ;;
count)
    echo "game=$(pad_pids -x game | head -1) host=$(pad_pids -x padglhost | head -1)" \
         "watch=$(pad_pids -f '^bash .*watch\.sh' | head -1) ball=$(pad_pids -f 'ballfeed[.]py' | head -1) led=$([ -e "$ROOT/dump/padled" ] && echo yes || echo no)" ;;
shot)
    bash "$R/glshot.sh" "$3" >/dev/null 2>&1 && echo ok || echo none ;;
root)
    echo "$ROOT" ;;
log)
    tail -6 "$PAD_LOGDIR/padball.log" 2>/dev/null ;;
esac
"""


def prepare(ref, tag):
    tree = os.path.join(WORK, "app_" + tag)
    if os.path.isdir(tree):
        import shutil
        shutil.rmtree(tree)
    os.makedirs(tree)
    arc = subprocess.run(["git", "-C", REPO, "archive", ref], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", tree.replace("\\", "/")], input=arc.stdout, check=True)
    with open(os.path.join(WORK, "rig.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write(HELPER_SH)
    return tree


def wsl_path(p):
    p = os.path.abspath(p)
    return "/mnt/%s%s" % (p[0].lower(), p[2:].replace("\\", "/"))


def helper(rig, *args, timeout=90):
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "-e", "bash", HELPER, rig]
                       + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    return ((r.stdout or "") + (r.stderr or "")).strip()


def counts(rig):
    out = {}
    for kv in helper(rig, "count").split():
        k, _, v = kv.partition("=")
        out[k] = v
    return out


def main():
    ref, out, tag = sys.argv[1], os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    tree = prepare(ref, tag)
    rig = wsl_path(os.path.join(tree, "tools", "spike2_emu"))
    print(helper(rig, "take"), flush=True)
    slot = open(os.path.join(WORK, "slot"), encoding="utf-8").read().strip()
    assert slot and slot != "0", "no rig of our own"
    log = open(os.path.join(WORK, tag + ".log"), "w", encoding="utf-8")

    def say(*a):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), " ".join(str(x) for x in a))
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    scratch = tempfile.mkdtemp(prefix="pad738-")
    launcher = os.path.join(scratch, "launch738.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % tree)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": CARD}, f)
    cfgdir = os.path.join(scratch, "cfg", "pinball_decryptor")
    os.makedirs(cfgdir, exist_ok=True)
    ctl = os.path.join(cfgdir, "audio_ctl.json")
    with open(ctl, "w", encoding="utf-8") as f:
        json.dump({"gain": 0.0, "muted": True}, f)
    tmp = os.path.join(scratch, "tmp")
    os.makedirs(tmp, exist_ok=True)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "TEMP": tmp, "TMP": tmp,
           "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "1", "PAD_RUNTIME": "0",
           "PAD_SLOT": slot, "PAD_TICKET": "", "PAD_LABEL": LABEL,
           "PAD_HIDDEN": "1", "PAD_AUDIO": "0"}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env,
                                        app_cmd=[sys.executable, launcher])
    say("tree", tree, "| rig", slot, "| server", url.split("?")[0], "| scratch", scratch)
    pf = None

    def tab():
        st = webui_shot.state(url).get("emulate", {})
        return ((st.get("run_btn") or {}).get("label"), st.get("vals", {}).get("state"))

    def shot(name):
        dst = os.path.join(out, "%s_game_%s.png" % (tag, name))
        r = helper(rig, "shot", wsl_path(dst))
        say("  game framebuffer", name, "->", dst if r == "ok" else "NO PICTURE (no renderer)")

    ok = True
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "emulate")
        time.sleep(5)
        webui_shot.api(url, "emulate.toggle")
        say("Start pressed")
        t0 = time.time()
        while time.time() - t0 < 420:
            if tab()[1] == "Game running" and counts(rig).get("game"):
                break
            time.sleep(3)
        else:
            say("RESULT %s: the game never came up" % tag)
            ok = False
            return
        c0 = counts(rig)
        say("game up:", c0, tab())
        time.sleep(20)                      # into attract
        shot("before_restart")

        # the export's own playfield, windowless, on this rig, with the app's
        # volume file - the bar an app-launched run shows
        root = helper(rig, "root")
        pf_env = dict(os.environ, PAD_SLOT=slot, PAD_LABEL=LABEL, PAD_PF_WINDOW="browser",
                      PAD_AUDIO_CTL=ctl, PAD_WSL_DISTRO="Ubuntu", PAD_ROOT_WSL=root,
                      PAD_ROOT=r"\\wsl.localhost\Ubuntu" + root.replace("/", "\\"))
        urlfile = os.path.join(scratch, "pf.url")
        pflaunch = os.path.join(scratch, "pf738.py")
        with open(pflaunch, "w", encoding="utf-8") as f:
            f.write(PF_LAUNCHER)
        pf = subprocess.Popen([sys.executable, pflaunch, urlfile,
                               os.path.join(tree, "tools", "spike2_emu", "playfield.py"),
                               GAME, "--savestates"],
                              stdout=open(os.path.join(scratch, "pf.log"), "w"),
                              stderr=subprocess.STDOUT, env=pf_env)
        for _ in range(120):
            if os.path.isfile(urlfile):
                break
            time.sleep(0.5)
        pf_url = open(urlfile, encoding="utf-8").read().split()[0]
        say("playfield page:", pf_url, "pid", pf.pid)

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1180, "height": 900})
            page.goto(pf_url)
            page.wait_for_timeout(8000)
            page.screenshot(path=os.path.join(out, "%s_playfield_before_restart.png" % tag))
            say("playfield bar:", page.evaluate(
                "Array.from(document.querySelectorAll('.pf-run .btn')).map(b => b.textContent)"))
            page.get_by_role("button", name="Restart game").click()
            say("RESTART GAME clicked on the playfield page")
            t0 = time.time()
            last, shots, back = None, set(), None
            while time.time() - t0 < 300:
                c = counts(rig)
                row = (pf.poll() is None, tab(), c.get("game"), c.get("host"),
                       c.get("watch"), c.get("led"))
                if row != last:
                    say("  %4ds playfield %s | app %r | game %s renderer %s watch %s led %s"
                        % (time.time() - t0, "UP" if row[0] else "GONE (exit %s)" % pf.poll(),
                           row[1], row[2] or "-", row[3] or "-", row[4] or "-", row[5]))
                    last = row
                el = time.time() - t0
                for mark in (4, 12, 30):
                    if el >= mark and mark not in shots:
                        shots.add(mark)
                        shot("restart_plus_%02ds" % mark)
                if el > 40 and row[1][1] == "Game running" and row[2] and row[2] != c0.get("game"):
                    back = row
                    break
                time.sleep(2)
            time.sleep(20)
            shot("restart_settled")
            alive = pf.poll() is None
            try:
                page.wait_for_timeout(3000)
                page.screenshot(path=os.path.join(out, "%s_playfield.png" % tag))
                say("shot", os.path.join(out, "%s_playfield.png" % tag))
            except Exception as exc:                     # noqa: BLE001
                say("playfield page shot failed:", exc)
            c1 = counts(rig)
            say("RESULT %s: game %s -> %s, renderer %s -> %s, watch.sh %s -> %s, playfield %s"
                % (tag, c0.get("game"), c1.get("game"), c0.get("host"), c1.get("host"),
                   c0.get("watch"), c1.get("watch"), "STILL OPEN" if alive else "CLOSED"))
            ok = bool(back) and alive
            # a game on the restarted boot, from the playfield page's own
            # Start: the switches reach the new game and the ball feeder
            # (started again with it) serves the ball
            if alive:
                page.get_by_role("button", name="Start", exact=True).click()
                say("START clicked on the playfield page")
                time.sleep(30)
                shot("game_started")
                say("ball feeder (padball.log):\n" + helper(rig, "log"))
                say("rig now:", counts(rig))
                page.screenshot(path=os.path.join(out, "%s_playfield_game.png" % tag))
            else:
                say("no playfield left to press Start on")
            browser.close()
        if tab()[0] == "Stop emulator":
            say("pressing Stop to end it")
            webui_shot.api(url, "emulate.toggle")
            time.sleep(25)
            say("after Stop: playfield", "UP" if pf.poll() is None else "closed")
    finally:
        if pf is not None and pf.poll() is None:
            pf.kill()
        proc.kill()
        say("released:", helper(rig, "release"))
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'wsl.exe'"
             " -and $_.CommandLine -like '*%s*' }"
             " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % wsl_path(tree)],
            capture_output=True, timeout=60)
        say("RESULT", tag, "OK" if ok else "FAILED")


if __name__ == "__main__":
    main()
