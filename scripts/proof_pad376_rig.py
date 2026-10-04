"""PAD-376 emulator proof: a blocks mode runs light shows and sets a lit shot's pace, through Try it.

    python scripts/proof_pad376_rig.py <out_dir> [slot]

Rebuilds in blocks the lights of KING GHIDORAH (sdk/examples/ghidorah_heads.c): its start show,
step by step (lightning, a strobe, a burst from the top, a fade), the Building lit blinking every
500 ms, then 250 ms with 8 s left and 100 ms with 4 s left, the Left ramp blinking faster as the
clock runs down (the kit's kit_hurry_ms), and a ready-made show (a rainbow) at the end. The app
(served headless from this tree) builds it with Try it on Godzilla LE 1.16, on a free rig slot
(never David's own: no PAD_TICKET), muted and hidden; a game is started, then Start mode now. The
mode's log (the show's steps over the game's placed inserts, and every insert it holds) is saved
in <out_dir>.
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
SLOT = sys.argv[2] if len(sys.argv) > 2 else "3"
RIGSH_WIN = r"C:\tmp\pad376_rig.sh"
RIGSH = "/mnt/c/tmp/pad376_rig.sh"
#: run a rig tool on slot 3 of the app's PAD-Runtime rig (written out at the start)
RIG_HELPER = """#!/bin/bash
export PAD_SLOT=%(slot)s PAD_LABEL=PAD-376 PAD_HOME=/mnt/wsl/paddata/spike2
RIG=%(rig)s
cd "$RIG" || exit 9
. "$RIG/padpath.sh"
case "$1" in
    shot)    bash glshot.sh "$2" ;;
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


def _step(fx, ms, a, b, at="center", rate=0, gi="keep"):
    return {"fx": fx, "ms": ms, "a": a, "b": b, "at": at, "rate": rate, "gi": gi}


def program(BM, slug, shots):
    p = BM.starter("GHIDORAH LIGHTS", shots)
    light = lambda shot, pattern, rate=None: {"op": "light_shot", "shot": shot, "color": "#ffb000",  # noqa: E731
                                              "pattern": pattern,
                                              "rate": None if rate is None else {"k": "num", "v": rate}}
    p.update({
        "name": "GHIDORAH LIGHTS", "seconds": 14, "ends_on_drain": False, "screen": False, "vars": [],
        "scripts": [
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "show", "show": "own", "steps": [
                    _step("bolts", 1500, "#ffb000", "#000000", "center", 190, "dark"),
                    _step("strobe", 500, "#ffffff", "#ffb000", "center", 60, "flash"),
                    _step("burst", 800, "#ffb000", "#ff4000", "top", 0, "dark"),
                    _step("fade", 400, "#ff4000", "#000000", "center")]},
                light("Building", "blink", 500), light("Left ramp", "hurry"),
                {"op": "log", "text": "GHIDORAH blocks: started"}]},
            {"hat": {"kind": "seconds_left", "seconds": 8}, "do": [light("Building", "blink", 250)]},
            {"hat": {"kind": "seconds_left", "seconds": 4}, "do": [light("Building", "blink", 100)]},
            {"hat": {"kind": "mode_end"}, "do": [{"op": "show", "show": "rainbow"}]},
        ]})
    return p


def main():
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)
    with open(RIGSH_WIN, "w", encoding="utf-8", newline="\n") as f:
        f.write(RIG_HELPER % {"slot": SLOT, "rig": win_to_wsl(os.path.join(REPO, "tools", "spike2_emu"))})
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad376rig-")
    project = os.path.join(scratch, "GZ 1.16 LE Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16"}, f)
    prof = MP.profile_for_card("godzilla_le", "1.16")
    slug, _ = BM.new_blocks_mode(project, "GHIDORAH LIGHTS", shots=[n for n, _m in prof.shots])
    folder = MP.mode_folder(project, slug)
    BM.save(project, slug, program(BM, slug, [n for n, _m in prof.shots]))
    print("mode", slug, "problems", BM.problems(BM.load(project, slug), folder=folder), flush=True)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch376.py")
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
           "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "1", "PAD_SLOT": SLOT, "PAD_TICKET": "",
           "PAD_LABEL": "PAD-374-check", "PAD_HIDDEN": "1", "PAD_AUDIO": "0"}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    print("server", url.split("?")[0], "scratch", scratch, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(3)
        webui_shot.api(url, "modes.select", slug, "code")
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
        webui_shot.api(url, "modes.start_now")
        time.sleep(26)                                # 14 s of mode, its end show, and some
        time.sleep(3)
        log = rig("modelog")[1]
        with open(os.path.join(out_dir, "mode.log"), "w", encoding="utf-8") as f:
            f.write(log)
        print("mode.log (own assets and the mode):", flush=True)
        for line in log.splitlines():
            if "GHIDORAH LIGHTS" in line or "own " in line or "heads" in line:
                print("   ", line[:220], flush=True)
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
