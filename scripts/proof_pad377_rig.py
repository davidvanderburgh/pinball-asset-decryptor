"""PAD-377 emulator proof: blocks share a value between modes, time in milliseconds and hold a
display priority, in the real game through Try it.

    python scripts/proof_pad377_rig.py <out_dir> [slot]

Two blocks modes in one project, built together with Try it on Godzilla LE 1.16 (rig slot 1 by
default, never David's own: no PAD_TICKET), muted and hidden:

- CHAIN (MASER BARRAGE's window): display priority 180, waits out a multiball. Its start starts
  a timer at 1500 ms; each time the timer runs out the window
  is 250 ms shorter and it starts again, so the mode log's stamps step 1500, 1250, 1000, 750, 500,
  250 ms. When the window is gone it sets the SHARED "maser won" to 1 and ends.
- LIT (FINAL WARS): display priority 190. Its start says whether "maser won" is set.

A game is started, then Start mode now on LIT (not lit), on CHAIN (the chain runs), on LIT again
(lit: CHAIN's value reached it). The mode log is saved in <out_dir>.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
CARD = (r"C:\Users\david\Documents\development\pinball-asset-decryptor\images\Stern\spike2"
        r"\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
RIGSH_WIN = r"C:\tmp\pad377_rig.sh"
RIGSH = "/mnt/c/tmp/pad377_rig.sh"
#: run a rig tool on the app's PAD-Runtime rig slot (written out at the start)
RIG_HELPER = """#!/bin/bash
export PAD_SLOT=%(slot)s PAD_LABEL=PAD-377 PAD_HOME=/mnt/wsl/paddata/spike2
RIG=%(rig)s
cd "$RIG" || exit 9
. "$RIG/padpath.sh"
case "$1" in
    coin)    python3 plunge.py coin 8 ;;
    game)    python3 plunge.py game ;;
    plunge)  python3 plunge.py plunge ;;
    modelog) cat "$PAD_HOME/padslots/%(slot)s/root/dump/mode.log" 2>/dev/null ;;
    ps)      ps -eo pid,etime,args | grep -E 'qemu|padglhost|watch.sh' | grep -v grep | cut -c1-160 ;;
esac
"""


def rig(*args, timeout=120):
    r = subprocess.run(["wsl", "-d", "PAD-Runtime", "-u", "root", "--", "bash", RIGSH] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def win_to_wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def programs():
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    var = lambda n: {"k": "var", "name": n}                         # noqa: E731
    chain = {
        "name": "CHAIN", "seconds": 30, "ends_on_drain": False, "screen": False,
        "wait_multiball": True, "priority": 180,
        "vars": [{"name": "window", "reset": "mode"}, {"name": "maser won", "reset": "game", "shared": True}],
        "timers": [{"name": "chain"}],
        "scripts": [
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "set", "var": "window", "value": num(1500)},
                {"op": "timer_start", "timer": "chain", "ms": var("window")},
                {"op": "log", "text": "CHAIN window 1500 ms"}]},
            {"hat": {"kind": "timer_done", "timer": "chain"}, "do": [
                {"op": "change", "var": "window", "by": num(-250)},
                {"op": "if", "cond": {"k": "cmp", "op": ">", "a": var("window"), "b": num(0)}, "then": [
                    {"op": "timer_start", "timer": "chain", "ms": var("window")},
                    {"op": "log", "text": "CHAIN ran out, 250 ms shorter"}],
                 "else": [
                    {"op": "set", "var": "maser won", "value": num(1)},
                    {"op": "log", "text": "CHAIN done: maser won"},
                    {"op": "end_mode"}]}]},
        ]}
    lit = {
        "name": "LIT", "seconds": 3, "ends_on_drain": False, "screen": False, "priority": 190,
        "vars": [{"name": "maser won", "reset": "game", "shared": True}],
        "scripts": [
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("maser won"), "b": num(1)},
                 "then": [{"op": "log", "text": "LIT by the other mode"}],
                 "else": [{"op": "log", "text": "NOT LIT yet"}]}]},
        ]}
    return chain, lit


def main():
    out_dir = os.path.abspath(sys.argv[1])
    slot = sys.argv[2] if len(sys.argv) > 2 else "1"
    os.makedirs(out_dir, exist_ok=True)
    with open(RIGSH_WIN, "w", encoding="utf-8", newline="\n") as f:
        f.write(RIG_HELPER % {"slot": slot, "rig": win_to_wsl(os.path.join(REPO, "tools", "spike2_emu"))})
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad377rig-")
    project = os.path.join(scratch, "GZ 1.16 LE Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16"}, f)
    prof = MP.profile_for_card("godzilla_le", "1.16")
    shots = [n for n, _m in prof.shots]
    slugs = []
    for p in programs():
        slug, _ = BM.new_blocks_mode(project, p["name"], shots=shots)
        BM.save(project, slug, p)
        print("mode", slug, "problems", BM.problems(BM.load(project, slug)), flush=True)
        slugs.append(slug)
    chain_slug, lit_slug = slugs
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch377.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % REPO)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes, "emulate_card": CARD,
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    cfgdir = os.path.join(scratch, "cfg", "pinball_decryptor")      # a rig run is always muted
    os.makedirs(cfgdir, exist_ok=True)
    with open(os.path.join(cfgdir, "audio_ctl.json"), "w", encoding="utf-8") as f:
        json.dump({"gain": 0.0, "muted": True}, f)
    import site
    tmp = os.path.join(scratch, "tmp")             # a Try it set of its own, never David's
    os.makedirs(tmp, exist_ok=True)
    env = {"PYTHONPATH": site.getusersitepackages(), "TEMP": tmp, "TMP": tmp,
           "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "1", "PAD_SLOT": slot, "PAD_TICKET": "",
           "PAD_LABEL": "PAD-377", "PAD_HIDDEN": "1", "PAD_AUDIO": "0"}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    print("server", url.split("?")[0], "scratch", scratch, flush=True)

    def start(slug, wait):
        webui_shot.api(url, "modes.select", slug, "code")
        time.sleep(2)
        webui_shot.api(url, "modes.start_now")
        time.sleep(wait)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(3)
        webui_shot.api(url, "modes.select", chain_slug, "code")
        time.sleep(2)
        print("rig before:", rig("ps")[1].strip() or "(nothing running)", flush=True)
        webui_shot.api(url, "modes.tryit")
        t0, last, ts = time.time(), None, {}
        while time.time() - t0 < 3600:
            ts = (webui_shot.state(url).get("modes", {}) or {}).get("tryit") or {}
            now = (ts.get("state"), (ts.get("reason") or "")[:200])
            if now != last:
                print("%5ds tryit %s" % (time.time() - t0, now), flush=True)
                last = now
            if ts.get("state") in ("live", "ended", "failed"):
                break
            time.sleep(10)
        if (ts.get("state") or "") != "live":
            return
        time.sleep(60)
        for k in ("coin", "game"):
            print(k, rig(k)[1].strip()[-200:], flush=True)
        time.sleep(25)
        rig("plunge")
        time.sleep(15)
        start(lit_slug, 6)          # not lit: nothing has set "maser won"
        start(chain_slug, 9)        # the chain: 1500 + 1250 + 1000 + 750 + 500 + 250 ms
        start(lit_slug, 6)          # lit by CHAIN's value
        log = rig("modelog")[1]
        with open(os.path.join(out_dir, "mode.log"), "w", encoding="utf-8") as f:
            f.write(log)
        print("mode.log (the two modes):", flush=True)
        stamps = []
        for line in log.splitlines():
            if re.search(r"\[(CHAIN|LIT)\]|display", line):
                print("   ", line[:220], flush=True)
            m = re.match(r"\s*(\d+) \[CHAIN\] (CHAIN window|CHAIN ran out|CHAIN done)", line)
            if m:
                stamps.append(int(m.group(1)))
        print("chain steps (ms):", [b - a for a, b in zip(stamps, stamps[1:])], flush=True)
    finally:
        try:
            webui_shot.api(url, "ui.select_tab", "emulate")
            st = webui_shot.state(url).get("emulate", {})
            if st.get("up") or st.get("running"):
                webui_shot.api(url, "emulate.toggle")
                time.sleep(20)
        except Exception as e:                        # noqa: BLE001
            print("stop:", e, flush=True)
        proc.terminate()
        print("rig after:", rig("ps")[1].strip() or "(nothing running)", flush=True)


if __name__ == "__main__":
    main()
