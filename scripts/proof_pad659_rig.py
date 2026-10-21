"""PAD-659 emulator proof: a card whose OS partition (p2) also carries /spk
boots, instead of failing with "mounted, but no directory in it holds a game
ELF".

    python scripts/proof_pad659_rig.py <card.raw> <out_dir>

<card.raw> is a copy of a stock card with ``debugfs -w -R "mkdir /spk"`` run on
its p2 (the reporter's card had that shape; no factory card does).  The app,
served headless from this tree, starts it on rig slot 4 (never David's own: no
PAD_TICKET), hidden and muted, waits for the game to reach attract mode, saves
a frame of the glass and the run's [card]/[watch] log lines in <out_dir>, and
stops the run.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
SLOT = "4"
RIGSH_WIN = r"C:\tmp\PAD-659\rig659.sh"
RIGSH = "/mnt/c/tmp/PAD-659/rig659.sh"
RIG_HELPER = """#!/bin/bash
export PAD_SLOT=%(slot)s PAD_LABEL=PAD-659-check PAD_HOME=/mnt/wsl/paddata/spike2
RIG=%(rig)s
cd "$RIG" || exit 9
. "$RIG/padpath.sh"
case "$1" in
    shot)    bash glshot.sh "$2" ;;
    ps)      ps -eo pid,etime,args | grep -E 'qemu|padglhost|watch.sh' | grep -v grep | cut -c1-160 ;;
esac
"""


def rig(*args, timeout=120):
    r = subprocess.run(["wsl", "-d", "PAD-Runtime", "-u", "root", "--", "bash", RIGSH] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def win_to_wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def log_lines(st):
    """The app's log pane, whatever shape the state carries it in."""
    shell = st.get("shell") or {}
    lines = shell.get("log") or st.get("log") or []
    out = []
    for ln in lines if isinstance(lines, list) else []:
        out.append(ln.get("text", "") if isinstance(ln, dict) else str(ln))
    return out


def main():
    card = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)
    with open(RIGSH_WIN, "w", encoding="utf-8", newline="\n") as f:
        f.write(RIG_HELPER % {"slot": SLOT,
                              "rig": win_to_wsl(os.path.join(REPO, "tools", "spike2_emu"))})
    scratch = tempfile.mkdtemp(prefix="pad659rig-")
    launcher = os.path.join(scratch, "launch659.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % REPO)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": card}, f)
    cfgdir = os.path.join(scratch, "cfg", "pinball_decryptor")   # a rig run is always muted
    os.makedirs(cfgdir, exist_ok=True)
    with open(os.path.join(cfgdir, "audio_ctl.json"), "w", encoding="utf-8") as f:
        json.dump({"gain": 0.0, "muted": True}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "",
           "PAD_UI_NO_PREREQS": "1", "PAD_SLOT": SLOT, "PAD_TICKET": "",
           "PAD_LABEL": "PAD-659-check", "PAD_HIDDEN": "1", "PAD_AUDIO": "0"}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], flush=True)
    seen = 0
    log = []
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "emulate")
        webui_shot.api(url, "ui.set", "emulate", "card", card)
        time.sleep(5)
        print("rig before:", rig("ps")[1].strip() or "(nothing on slot 4)", flush=True)
        webui_shot.api(url, "emulate.toggle")
        t0, last = time.time(), None
        while time.time() - t0 < 1500:
            st = webui_shot.state(url)
            em = st.get("emulate") or {}
            now = (em.get("vals") or {}).get("state")
            lines = log_lines(st)
            for ln in lines[seen:]:
                if "[card]" in ln or "[watch]" in ln or "ELF" in ln:
                    print("   log:", ln[:200], flush=True)
            seen = len(lines)
            log = lines
            if now != last:
                print("%5ds state %r" % (time.time() - t0, now), flush=True)
                last = now
            if now and ("ttract" in now or "high score" in now.lower()):
                break
            # the tab's state line is no guide to a slot run's boot (it read
            # "Not running" with the game up on PAD-659's proof): a fixed spell
            if time.time() - t0 > 420:
                break
            time.sleep(5)
        g = os.path.join(out_dir, "glass_attract.png")
        print("shot:", rig("shot", win_to_wsl(g))[1].strip()[-200:], flush=True)
        print("rig now:", rig("ps")[1].strip()[-600:], flush=True)
    finally:
        try:
            st = webui_shot.state(url).get("emulate", {})
            if (st.get("vals") or {}).get("state") not in (None, "Not running", "—"):
                webui_shot.api(url, "emulate.toggle")
                time.sleep(25)
        except Exception as e:                        # noqa: BLE001
            print("stop:", e, flush=True)
        proc.terminate()
        print("rig after:", rig("ps")[1].strip() or "(nothing on slot 4)", flush=True)


if __name__ == "__main__":
    main()
