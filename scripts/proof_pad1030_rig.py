"""PAD-1030 emulator proof: a blocks mode with 20 clips of its own on James Bond LE 1.06, through Try it.

    python scripts/proof_pad1030_rig.py <out_dir>

The Bond owner's DIAMOND DEATH THREAT had 13 clips; the 13th, background2 looping behind the HUD, never played
(the limit was 12). Here the mode carries 20: crem1..crem19 (green cards, crem11 red) and background2 (blue) last.
When the mode starts it plays crem11 full screen, then background2 behind the HUD, over and over. The clips are
plain colour cards made with ffmpeg, so nothing of a film is used. The app (served headless from this tree) builds
it with Try it, pinned to rig slot 4 (never David's own: no PAD_TICKET), muted and hidden; a game is started, then
Start mode now. The mode's log, its .assets file and the guest's frames (colour counts) are saved in <out_dir>.

Round 2 (the owner on v1.351.1, 12 clips: still the game's circles, in both modes), each shot made while the mode
runs is watched too, and these bring the run nearer their card (any mix):
    PROOF_BAR=1        its name in the game's bar and an info line (SUPER JACKPOT)
    PROOF_SOUND=1      a sound of its own with the opening clip
    PROOF_MULTI=1      their three blocks modes by name (DIAMOND DEATH THREAT lights a shot, runs Sparkles; BOND VS
                       SUMO holds the right return up post with its clock waiting); PROOF_START=<slug> picks one
    PROOF_FORMS=1      and their four Movie Wizard form modes, a clip each
    PROOF_SHOTSTART=1  started by its start shot (three right ramp enters), not Start mode now
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
if __name__ == "__main__":          # a build's worker pool spawns this file again: no second server there
    from pinball_decryptor.webui import host
    sys.argv = ["host"] + sys.argv[1:]
    sys.exit(host.main())
'''
CARD = r"D:\Pinball\images\Stern\spike2\james_bond_le-1_06_0.Release.16G.sdcard.raw"
SLOT = "4"
RIGSH_WIN = r"C:\tmp\pad1030_rig.sh"
RIGSH = "/mnt/c/tmp/pad1030_rig.sh"
#: run a rig tool on the proof's slot of the app's PAD-Runtime rig (written out at the start)
RIG_HELPER = """#!/bin/bash
export PAD_SLOT=%(slot)s PAD_LABEL=PAD-1030-check PAD_HOME=/mnt/wsl/paddata/spike2
RIG=%(rig)s
cd "$RIG" || exit 9
. "$RIG/padpath.sh"
case "$1" in
    shot)    bash glshot.sh "$2" ;;
    coin)    python3 plunge.py coin 8 ;;
    game)    python3 plunge.py game ;;
    plunge)  python3 plunge.py plunge ;;
    press)   python3 swpoke.py "$2" "${3:-150}" ;;
    modelog) cat "$PAD_HOME/padslots/%(slot)s/root/dump/mode.log" 2>/dev/null ;;
    assets)  cat "$PAD_HOME"/padslots/%(slot)s/root/usr/local/padmode/*.assets 2>/dev/null ;;
    ps)      ps -eo pid,etime,args | grep -E 'qemu|padglhost|watch.sh' | grep "padslots/%(slot)s" | grep -v grep | cut -c1-160 ;;
esac
"""
CLIPS = ["crem%d" % i for i in range(1, 20)] + ["background2"]
#: (switch, words) made one after another while the mode runs (james_bond_le-1.06.port)
SHOTS = [(46, "right ramp enter"), (48, "right ramp exit"), (50, "db5 roof"), (57, "tank target"),
         (47, "side ramp enter"), (55, "left spinner"), (55, "left spinner"), (49, "side ramp target")]
COLOUR_OF = {"crem11": "0xff0000", "background2": "0x0000ff"}             # the rest green


def rig(*args, timeout=120):
    r = subprocess.run(["wsl", "-d", "PAD-Runtime", "-u", "root", "--", "bash", RIGSH] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def win_to_wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def counts(png):
    """How many pixels of each card's colour the frame holds."""
    from PIL import Image
    im = Image.open(png).convert("RGB")
    out = {"red": 0, "blue": 0, "green": 0}
    for r, g, b in im.getdata():
        if r > 200 and g < 60 and b < 60:
            out["red"] += 1
        elif b > 200 and r < 60 and g < 60:
            out["blue"] += 1
        elif g > 200 and r < 60 and b < 60:
            out["green"] += 1
    return out


def media(folder, clips=CLIPS):
    for name in clips:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=%s:s=1280x720:r=30:d=%d" % (COLOUR_OF.get(name, "0x00ff00"),
                                                             3 if name == "crem11" else 4),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(folder, name + ".mp4")],
                       check=True)
    for name, (hz, secs) in {"crem11": (440, 3), "crem22": (660, 2)}.items():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=%d:duration=%d:sample_rate=48000" % (hz, secs), "-ac", "2",
                        os.path.join(folder, name + ".wav")], check=True)


def program(BM, shots):
    p = BM.starter("DIAMOND", shots)
    p.update({
        "name": "DIAMOND", "seconds": 120, "ends_on_drain": False, "screen": False, "vars": [],
        "clips": [{"name": n, "file": n + ".mp4"} for n in CLIPS],
        "sounds": [], "music": "",
        "scripts": [
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "clip", "clip": "crem11", "where": "full"},
                {"op": "clip", "clip": "background2", "where": "loop"},
                {"op": "log", "text": "DIAMOND blocks: started"}]},
        ]})
    if os.environ.get("PROOF_BAR") == "1":            # as the reporter's: its name in the game's bar, an info line
        p["bar"] = dict(p.get("bar") or {}, on=True, color="#0000c0")
        p["vars"] = [{"name": "superjackpot", "start": 20000000}]
        p["info"] = {"on": True, "text": "SUPER JACKPOT", "value": {"k": "var", "name": "superjackpot"}}
    if os.environ.get("PROOF_SOUND") == "1":          # as the reporter's: a sound of its own with the opening clip
        p["sounds"] = [{"name": "crem11", "file": "crem11.wav", "priority": 4},
                       {"name": "crem22", "file": "crem22.wav", "priority": 4}]
        p["scripts"][0]["do"].insert(1, {"op": "sound", "sound": "crem11", "fallback": ""})
    return p


#: PROOF_MULTI=1, the reporter's card as their screenshots show it: three blocks modes, each with its own clips, a sound
#: and a loop behind the HUD; DIAMOND DEATH THREAT lights a shot and runs Sparkles, BOND VS SUMO holds the right return
#: up post 8 s with its clock waiting. PROOF_START names the one started (its slug): diamond_death_threat by default.
BVS_CLIPS = ["bvs_000v"] + ["bvs_%d" % i for i in range(1, 11)] + ["background"]
FW_CLIPS = ["fw_loop"]


def multi_card(BM, MP, project, shots, started):
    """The three modes; returns {slug: folder}. Each starts on its third right ramp enter (the starter's), the
    ones not ``started`` on their 99th."""
    COLOUR_OF.update({"bvs_000v": "0xff0000", "background": "0x0000ff"})
    out = {}
    for name, clips in (("DIAMOND DEATH THREAT", CLIPS), ("BOND VS SUMO", BVS_CLIPS), ("FILM WIZARDS", FW_CLIPS)):
        slug, _ = BM.new_blocks_mode(project, name, shots=shots)
        folder = MP.mode_folder(project, slug)
        media(folder, clips)
        p = BM.starter(name, shots)
        p.update({"name": name, "seconds": 120, "ends_on_drain": False, "screen": False,
                  "clips": [{"name": n, "file": n + ".mp4"} for n in clips], "music": ""})
        num = lambda v: {"k": "num", "v": v}                            # noqa: E731
        if name == "DIAMOND DEATH THREAT":
            p["vars"] += [{"name": "diamondaward", "reset": "mode"}]
            p["sounds"] = [{"name": "crem11", "file": "crem11.wav", "priority": 4},
                           {"name": "crem22", "file": "crem22.wav", "priority": 4}]
            start = [{"op": "set", "var": "diamondaward", "value": num(0)},
                     {"op": "light_shot", "shot": shots[1], "color": "#0000ff", "pattern": "blink"},
                     {"op": "clip", "clip": "crem11", "where": "full"},
                     {"op": "sound", "sound": "crem11", "fallback": ""},
                     {"op": "clip", "clip": "background2", "where": "loop"},
                     {"op": "show", "show": "sparkle"}]
        elif name == "BOND VS SUMO":
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=frequency=550:duration=3:sample_rate=48000", "-ac", "2",
                            os.path.join(folder, "bvs_000.wav")], check=True)
            p["vars"] += [{"name": "awards", "reset": "mode"}, {"name": "superjackpot", "start": 22000000}]
            p["sounds"] = [{"name": "bvs_000", "file": "bvs_000.wav", "priority": 4}]
            start = [{"op": "set", "var": "awards", "value": num(0)},
                     {"op": "set", "var": "superjackpot", "value": num(22000000)},
                     {"op": "log", "text": "YOLT Mini Wizard Mode"},
                     {"op": "clip", "clip": "bvs_000v", "where": "full"},
                     {"op": "sound", "sound": "bvs_000", "fallback": ""},
                     {"op": "clip", "clip": "background", "where": "loop"},
                     {"op": "hold", "what": "right_return_up", "ms": num(8000), "clock": "wait"}]
        else:
            p["sounds"] = []
            start = [{"op": "clip", "clip": "fw_loop", "where": "loop"}]
        for s in p["scripts"]:
            if (s.get("hat") or {}).get("kind") == "mode_start":
                s["do"] = start
            elif (s.get("hat") or {}).get("when") == "idle" and slug != started:
                s["do"][0]["cond"]["b"] = num(99)        # the started one's three start shots start only it
        BM.save(project, slug, p)
        print("mode", slug, "problems", BM.problems(BM.load(project, slug), folder=folder), flush=True)
        out[slug] = folder
    if os.environ.get("PROOF_FORMS") == "1":   # the reporter's four Movie Wizard modes beside them: form modes, a clip each
        for film in ("From Russia", "Dr No", "Goldfinger", "Thunderball"):
            spec = MP.blank_spec(MP.profile_for_card("james_bond_le", "1.06"), "Movie Wizard - " + film)
            spec.start_shot, spec.start_count, spec.clip = shots[5], 99, "title"
            slug, _ = MP.new_mode(project, spec=spec)
            out[slug] = MP.mode_folder(project, slug)
            print("form mode", slug, flush=True)
    return out


def main():
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)
    with open(RIGSH_WIN, "w", encoding="utf-8", newline="\n") as f:
        f.write(RIG_HELPER % {"slot": SLOT, "rig": win_to_wsl(os.path.join(REPO, "tools", "spike2_emu"))})
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad1030rig-")
    project = os.path.join(scratch, "Bond LE 1.06 Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.06"}, f)
    prof = MP.profile_for_card("james_bond_le", "1.06")
    shots = [n for n, _m in prof.shots]
    if os.environ.get("PROOF_MULTI") == "1":
        slug = os.environ.get("PROOF_START") or "diamond_death_threat"
        multi_card(BM, MP, project, shots, slug)
    else:
        slug, _ = BM.new_blocks_mode(project, "DIAMOND", shots=shots)
        folder = MP.mode_folder(project, slug)
        media(folder)
        BM.save(project, slug, program(BM, shots))
        print("mode", slug, "problems", BM.problems(BM.load(project, slug), folder=folder), flush=True)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch1030.py")
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
           "PAD_LABEL": "PAD-1030-check", "PAD_HIDDEN": "1", "PAD_AUDIO": "0"}
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
        time.sleep(90)
        for k in ("coin", "game"):
            print(k, rig(k)[1].strip()[-200:], flush=True)
        time.sleep(25)
        rig("plunge")
        time.sleep(15)
        g = os.path.join(out_dir, "glass_before_mode.png")
        rig("shot", win_to_wsl(g))
        if os.path.isfile(g):
            print("before the mode:", counts(g), flush=True)
        if os.environ.get("PROOF_SHOTSTART") == "1":     # as a player starts it: its start shot, three times, the
            for _ in range(3):                           # game's own clip for each shot on the TV as it starts
                rig("press", "46", "150")
                time.sleep(1.2)
        else:
            webui_shot.api(url, "modes.start_now")
        t1 = time.time()
        for i, at in enumerate((0.3, 1.0, 2.0, 3.0, 4.5, 6.0, 8.0, 10.0, 13.0, 16.0, 20.0, 25.0)):
            time.sleep(max(0.0, t1 + at - time.time()))
            g = os.path.join(out_dir, "glass_mode_%02d.png" % i)
            rig("shot", win_to_wsl(g))
            if os.path.isfile(g):
                print("  t+%5.1fs %s %s" % (time.time() - t1, os.path.basename(g), counts(g)), flush=True)
        # round 2 (the reporter on v1.351.1: the game's circles, not the loop, "during the mode when nothing is hit"):
        # shots made while the mode runs, the game's own reactions to them on the TV, and what comes back after
        for k, (sw, words) in enumerate(SHOTS):
            rig("press", str(sw), "150")
            t2 = time.time()
            for at in (1.5, 4.0, 7.0):
                time.sleep(max(0.0, t2 + at - time.time()))
                g = os.path.join(out_dir, "shot_%02d_%s_%04.1fs.png" % (k, words.replace(" ", "_"), at))
                rig("shot", win_to_wsl(g))
                if os.path.isfile(g):
                    print("  shot %d %-22s +%4.1fs %s" % (k, words, at, counts(g)), flush=True)
        time.sleep(3)
        with open(os.path.join(out_dir, "assets.txt"), "w", encoding="utf-8") as f:
            f.write(rig("assets")[1])
        log = rig("modelog")[1]
        with open(os.path.join(out_dir, "mode.log"), "w", encoding="utf-8") as f:
            f.write(log)
        print("mode.log (own assets and the mode):", flush=True)
        for line in log.splitlines():
            if "DIAMOND" in line or "own " in line or "diamond" in line:
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
