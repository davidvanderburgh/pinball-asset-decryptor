r"""PAD-735 proof: the Emulate tab's Restart game, on a real emulator run.

    python scripts/proof_pad735_restart.py <git ref> <out dir> <tag> [--restart]

<git ref> is exported to %TEMP%\PAD-735\app_<tag> (main for "before", the ticket
branch for "after") and served as the real app, hidden and muted, on a rig this
script takes under the app's own label (riglock.sh take --any PAD-735) and gives
back, in Ubuntu (PAD_RUNTIME=0). The card is stock godzilla_pro 1.16.

The app presses Start and waits for "Game running"; <tag>_emulate_running.png is
the tab then. With --restart it goes on:
  1. presses Restart game (the tab's button, emulate.restart), and logs the one
     button, the State and the rig's game pid every 2 s until the game is
     running again under a NEW pid;
  2. asks again the way the playfield window does - RunCtl.ask_restart(),
     the window's own code, writing its request beside the app's volume
     file - and checks the same stop-and-start follows.
Then Stop, and the rig goes back.
"""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

#: under the Windows profile: a rig outside it keeps its board in WSL's home,
#: not the one the app and the dashboard read (padpath.sh pad_board_dir)
WORK = r"C:\Users\david\AppData\Local\Temp\PAD-735"
CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
HELPER = "/mnt/c/Users/david/AppData/Local/Temp/PAD-735/rig.sh"
LABEL = "PAD-735"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui.tabs import emulate
emulate.EmulateTab._precache_kick = lambda self: None
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
#: run as root in Ubuntu: <rig dir> take|release|count
HELPER_SH = r"""#!/bin/bash
R=$1
export HOME=/home/david
case "$2" in
take)
    out=$(sudo -u david -H bash "$R/riglock.sh" take --any PAD-735 "PAD-735 Restart game proof" 2>&1)
    echo "$out"
    printf '%s\n' "$out" | grep -o 'slot=[0-9]*' | head -1 | cut -d= -f2 > /mnt/c/Users/david/AppData/Local/Temp/PAD-735/slot
    exit 0 ;;
esac
SLOT=$(cat /mnt/c/Users/david/AppData/Local/Temp/PAD-735/slot 2>/dev/null)
case "$SLOT" in ''|0|*[!0-9]*) echo "no rig of our own (slot '$SLOT'): refusing" >&2; exit 2 ;; esac
export PAD_HOME=/home/david PAD_SLOT=$SLOT
. "$R/padpath.sh"
case "$2" in
release)
    PAD_LABEL=PAD-735 bash "$R/killgame.sh" >/dev/null 2>&1
    find "$PAD_HOME/padslots/$SLOT/root/data" "$PAD_HOME/padslots/$SLOT/root/dump" \
        -user root -exec chown -h david:david {} + 2>/dev/null
    sudo -u david -H bash "$R/riglock.sh" release "$SLOT" PAD-735 ;;
count)
    echo "game=$(pad_pids -x game | head -1) host=$(pad_count -x padglhost) watch=$(pad_count -f '^bash .*watch\.sh')" ;;
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
    do_restart = "--restart" in sys.argv[4:]
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

    scratch = tempfile.mkdtemp(prefix="pad735-")
    launcher = os.path.join(scratch, "launch735.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % tree)
    settings = os.path.join(scratch, "settings.json")
    import json
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
           "PAD_SLOT": slot, "PAD_TICKET": "", "PAD_LABEL": LABEL,
           "PAD_HIDDEN": "1", "PAD_AUDIO": "0"}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env,
                                        app_cmd=[sys.executable, launcher])
    say("tree", tree, "| rig", slot, "| server", url.split("?")[0], "| scratch", scratch)

    def tab():
        st = webui_shot.state(url).get("emulate", {})
        return ((st.get("run_btn") or {}).get("label"), st.get("vals", {}).get("state"))

    def wait_running(limit, since=None):
        """Until the State says Game running under a game pid other than
        <since>; logs every change. Returns the pid, or None."""
        t0, last = time.time(), None
        while time.time() - t0 < limit:
            now = tab()
            c = counts(rig)
            row = (now, c.get("game"))
            if row != last:
                say("  %4ds button %-18r state %-24r game pid %s"
                    % (time.time() - t0, now[0], now[1], c.get("game") or "-"))
                last = row
            if now[1] == "Game running" and c.get("game") and c.get("game") != since:
                return c.get("game")
            time.sleep(2)
        return None

    ok = True
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(5)
            say("idle:", tab(), "| rig:", counts(rig))
            webui_shot.api(url, "emulate.toggle")
            say("Start pressed")
            pid = wait_running(420)
            if not pid:
                say("RESULT %s: the game never came up" % tag)
                ok = False
                return
            say("game up, pid", pid, tab())
            time.sleep(3)
            # the card box's footer, where Start / Stop emulator sits
            page.evaluate("document.querySelector('.emu-run')"
                          ".scrollIntoView({block: 'center'})")
            time.sleep(1)
            path = os.path.join(out, "%s_emulate_running.png" % tag)
            page.screenshot(path=path)
            say("shot", path)
            if do_restart:
                say("RESTART GAME pressed (emulate.restart) ->",
                    webui_shot.api(url, "emulate.restart"))
                time.sleep(0.5)
                say("  right after:", tab())
                pid2 = wait_running(420, since=pid)
                say("RESULT tab restart: %s" % ("game running again, pid %s -> %s"
                                                % (pid, pid2) if pid2 else "NOT back"))
                ok = ok and bool(pid2)
                if pid2:
                    # the playfield window's own code asks, as its button does
                    sys.path.insert(0, os.path.join(tree, "tools", "spike2_emu"))
                    os.environ["PAD_SLOT"] = slot
                    import playfield as pf
                    run = pf.RunCtl(os.path.join(cfgdir, "audio_ctl.json"))
                    say("PLAYFIELD WINDOW asks (RunCtl.ask_restart) ->", run.ask_restart(),
                        pf.restart_req_path(run.ctl_path))
                    pid3 = wait_running(420, since=pid2)
                    say("RESULT window restart: %s" % ("game running again, pid %s -> %s"
                                                       % (pid2, pid3) if pid3 else "NOT back"))
                    ok = ok and bool(pid3)
            lines = page.evaluate(
                "Array.from(document.querySelectorAll('.line')).map(e => e.textContent)")
            for ln in lines:
                if "restart" in ln.lower() or "playfield window asked" in ln:
                    say("  log:", ln[:200])
            if tab()[0] == "Stop emulator":
                say("pressing Stop to end it")
                webui_shot.api(url, "emulate.toggle")
                time.sleep(25)
            browser.close()
    finally:
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
