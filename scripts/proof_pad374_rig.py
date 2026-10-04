"""PAD-374 emulator proof: a blocks mode plays its OWN clips and sounds, through Try it.

    python scripts/proof_pad374_rig.py <out_dir>

Rebuilds in blocks the part of KING GHIDORAH (sdk/examples/ghidorah_heads.c) that plays the
mode's own assets: its music bed and an intro full screen then a loop behind the HUD when it
starts, a clip behind the HUD and a call on each "sever" (here every 3 seconds), and at the
end a call (else the game's Time is up) and a clip full screen. The clips are plain colour
cards (intro red, loop blue, sever green, won magenta) and the sounds tones, made here with
ffmpeg, so nothing of a film is used. The app (served headless from this tree) builds it with
Try it on Godzilla LE 1.16, pinned to rig slot 3 (never David's own: no PAD_TICKET), muted
and hidden; a game is started, then Start mode now. The mode's log and the guest's frames
(colour counts) are saved in <out_dir>.
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
SLOT = "3"
RIGSH_WIN = r"C:\tmp\pad374_rig.sh"
RIGSH = "/mnt/c/tmp/pad374_rig.sh"
#: run a rig tool on slot 3 of the app's PAD-Runtime rig (written out at the start)
RIG_HELPER = """#!/bin/bash
export PAD_SLOT=%(slot)s PAD_LABEL=PAD-374-check PAD_HOME=/mnt/wsl/paddata/spike2
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
COLOURS = {"intro": "red", "loop": "blue", "sever": "green", "won": "magenta"}


def rig(*args, timeout=120):
    r = subprocess.run(["wsl", "-d", "PAD-Runtime", "-u", "root", "--", "bash", RIGSH] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def win_to_wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def counts(png):
    """How many pixels of each clip's colour the frame holds."""
    from PIL import Image
    im = Image.open(png).convert("RGB")
    out = {"red": 0, "blue": 0, "green": 0, "magenta": 0}
    for r, g, b in im.getdata():
        if r > 200 and g < 60 and b < 60:
            out["red"] += 1
        elif b > 200 and r < 60 and g < 60:
            out["blue"] += 1
        elif g > 200 and r < 60 and b < 60:
            out["green"] += 1
        elif r > 200 and b > 200 and g < 60:
            out["magenta"] += 1
    return out


def media(folder):
    ff = "ffmpeg"
    for name, colour in COLOURS.items():
        secs = {"intro": 3, "loop": 4, "sever": 2, "won": 3}[name]
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=%s:s=1280x720:r=30:d=%d" % ("0xff00ff" if colour == "magenta" else
                                                             {"red": "0xff0000", "blue": "0x0000ff",
                                                              "green": "0x00ff00"}[colour], secs),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(folder, name + ".mp4")],
                       check=True)
    for name, (hz, secs) in {"sever": (880, 1), "lost": (330, 1), "music": (220, 20)}.items():
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=%d:duration=%d:sample_rate=48000" % (hz, secs), "-ac", "2",
                        os.path.join(folder, name + ".wav")], check=True)


def program(BM, slug, shots):
    p = BM.starter("HEADS", shots)
    p.update({
        "name": "HEADS", "seconds": 14, "ends_on_drain": False, "screen": False, "vars": [],
        "clips": [{"name": n, "file": n + ".mp4"} for n in COLOURS],
        "sounds": [{"name": "sever", "file": "sever.wav", "priority": 4},
                   {"name": "lost", "file": "lost.wav", "priority": 4}],
        "music": "music.wav",
        "scripts": [
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "clip", "clip": "intro", "where": "full"},
                {"op": "clip", "clip": "loop", "where": "loop"},
                {"op": "log", "text": "HEADS blocks: started"}]},
            {"hat": {"kind": "every", "seconds": 6}, "do": [
                {"op": "clip", "clip": "sever", "where": "behind"},
                {"op": "sound", "sound": "sever"}]},
            {"hat": {"kind": "mode_end"}, "do": [
                {"op": "sound", "sound": "lost", "fallback": "time_up"},
                {"op": "clip", "clip": "won", "where": "full"}]},
        ]})
    return p


def main():
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)
    with open(RIGSH_WIN, "w", encoding="utf-8", newline="\n") as f:
        f.write(RIG_HELPER % {"slot": SLOT, "rig": win_to_wsl(os.path.join(REPO, "tools", "spike2_emu"))})
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad374rig-")
    project = os.path.join(scratch, "GZ 1.16 LE Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16"}, f)
    prof = MP.profile_for_card("godzilla_le", "1.16")
    slug, _ = BM.new_blocks_mode(project, "HEADS", shots=[n for n, _m in prof.shots])
    folder = MP.mode_folder(project, slug)
    media(folder)
    BM.save(project, slug, program(BM, slug, [n for n, _m in prof.shots]))
    print("mode", slug, "problems", BM.problems(BM.load(project, slug), folder=folder), flush=True)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch374.py")
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
        g = os.path.join(out_dir, "glass_before_mode.png")
        rig("shot", win_to_wsl(g))
        if os.path.isfile(g):
            print("before the mode:", counts(g), flush=True)
        webui_shot.api(url, "modes.start_now")
        t1 = time.time()
        for i, at in enumerate((0.3, 1.2, 2.2, 3.5, 4.5, 6.6, 7.5, 9.0, 12.0, 14.7, 15.6, 17.0, 19.0)):
            time.sleep(max(0.0, t1 + at - time.time()))
            g = os.path.join(out_dir, "glass_mode_%02d.png" % i)
            rig("shot", win_to_wsl(g))
            if os.path.isfile(g):
                print("  t+%5.1fs %s %s" % (time.time() - t1, os.path.basename(g), counts(g)), flush=True)
        time.sleep(3)
        log = rig("modelog")[1]
        with open(os.path.join(out_dir, "mode.log"), "w", encoding="utf-8") as f:
            f.write(log)
        print("mode.log (own assets and the mode):", flush=True)
        for line in log.splitlines():
            if "HEADS" in line or "own " in line or "heads" in line:
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
