"""PAD-443 proof shots: "Find originals…" on the Audio and Images tabs.

    python scripts/shot_pad443.py <repo> <out_dir> [--after]

Builds a scratch Godzilla project the way "Transfer Mods to New Version" from
an extract of a built card leaves one: every replacement picked on the Audio
and Images tabs is the CARD'S OWN COPY, a file in that old extract.  Beside it
sits a folder of the modder's own files under names of their own: sounds at
48 kHz / FLAC / MP3, pictures as black-and-white masters at twice the size.
The copies were made from them the way a Write makes them (sounds gained and
run through a lossy codec, pictures stretched to the slot and squeezed into
BC3).  Photographed under the same names before and after:

- audio_find_originals.png   Audio tab.  Before (main): no way to find the
                             files.  After: "Find originals…" pressed and the
                             folder searched: every copy paired with its file.
- images_find_originals.png  Images tab, the same.

Needs Playwright (the user site-packages one), the installed Edge, ffmpeg,
a stock Godzilla 1.16 audio extract (PAD443_STOCK_AUDIO) and the Godzilla
project's scene pictures (PAD443_PICTURES).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

STOCK_AUDIO = os.environ.get(
    "PAD443_STOCK_AUDIO",
    r"C:\tmp\pad151\godzilla_le-1_16_0_spike2.Release.8G.sdcard\audio")
PICTURES = os.environ.get(
    "PAD443_PICTURES",
    r"C:\Users\david\OneDrive\Desktop\gzho\images\scene_textures")

#: slot <- the stock sound the modder's own file is (a sound from elsewhere
#: on the card stands in for a custom one), its name and type in his folder
SOUNDS = [
    ("idx0790 - SE GZ FX M3 GODZILLA ROAR.wav", "idx2302 - SE GZ FX TUNE BOC AWARD 1.wav", "Heisei roar - final.wav"),
    ("idx1968 - SE GZ FX M2 TRANSFORMER POP 2.wav", "idx1350 - SE GZ FX M2 JETS FLYBY 1.wav", "Maser flyby v3.flac"),
    ("idx1337 - SE GZ FX DE O2DESTROYER FAIL.wav", "idx0624 - SE GZ FX M9 GABARA SCREECH.wav", "Destoroyah screech.mp3"),
    ("idx1639 - SE GZ FX M1 CROWD SCREAMS 1.wav", "idx1979 - SE GZ FX M1 CROWD SCREAMS 2.wav", "Tokyo crowd (long take).wav"),
    ("idx2398 - SE GZ FX TANK FIRE SINGLE DISTANT 3.wav", "idx1370 - SE GZ FX MISSILE LAUNCH 8.wav", "Type 90 tank - distant.wav"),
    ("idx1713 - SE GZ FX M1 GEIGER COUNTER.wav", "idx0181 - SE GZ FX DE KUMONGA16.wav", "Geiger counter BW mix.flac"),
    ("idx1753 - SE GZ FX SCOOP KICKOUT 1.wav", "idx0660 - SE GZ FX DE BALL SAVED 3.wav", "Scoop kick orchestral.wav"),
    ("idx1607 - SE GZ FX MECHAGODZILLA HIT 1.wav", "idx1852 - SE GZ FX M12 JET JAGUAR SHORT 1.wav", "Kiryu hit.mp3"),
]
#: and the stock sounds that are only there to fill the list
FILLER = 24
#: unrelated files of the modder's own in the same folder
NOISE = ["idx0209.wav", "idx0186.wav", "idx0448.wav", "idx1594.wav"]


def _ffmpeg():
    sys.path.insert(0, REPO)
    from pinball_decryptor.core.audio import find_ffmpeg
    return find_ffmpeg()


def _baseline(root, rels):
    lines = []
    for rel in rels:
        with open(os.path.join(root, *rel.split("/")), "rb") as f:
            lines.append("%s\t%s\n" % (rel, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(root, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)


def _stock_names():
    return sorted(f for f in os.listdir(STOCK_AUDIO) if f.endswith(".wav"))


def _sounds(scratch, project, old, mine):
    ff = _ffmpeg()
    names = _stock_names()
    used = {s for s, _o, _n in SOUNDS}
    filler = [n for n in names if " - SE GZ FX" in n and n not in used][:FILLER]
    rels = []
    for n in sorted(used) + filler:
        shutil.copy2(os.path.join(STOCK_AUDIO, n), os.path.join(project, "audio", n))
        rels.append("audio/" + n)
    picks = {}
    for slot, own, name in SOUNDS:
        dst = os.path.join(mine, "Sounds", name)
        ext = os.path.splitext(name)[1]
        args = {".wav": ["-ar", "48000", "-c:a", "pcm_s24le"],
                ".flac": ["-ar", "48000"],
                ".mp3": ["-c:a", "libmp3lame", "-b:a", "192k"]}[ext]
        subprocess.run([ff, "-v", "error", "-y", "-i",
                        os.path.join(STOCK_AUDIO, own)] + args + [dst], check=True)
        # the card's copy: gained to the slot, through a lossy codec, 44.1 kHz
        copy = os.path.join(old, "audio", slot)
        ogg = os.path.join(scratch, "tmp.ogg")
        subprocess.run([ff, "-v", "error", "-y", "-i", dst, "-af",
                        "volume=-4dB", "-c:a", "libvorbis", "-q:a", "3",
                        "-ar", "44100", ogg], check=True)
        subprocess.run([ff, "-v", "error", "-y", "-i", ogg, "-c:a",
                        "pcm_s16le", copy], check=True)
        os.remove(ogg)
        picks["audio/" + slot] = copy
    for n in NOISE:
        shutil.copy2(os.path.join(STOCK_AUDIO, n),
                     os.path.join(mine, "Sounds", "outtake " + n.split(".")[0] + ".wav"))
    return rels, picks


def _pictures(project, old, mine):
    sys.path.insert(0, REPO)
    import numpy as np
    from PIL import Image, ImageOps
    from pinball_decryptor.plugins.stern import dds
    names = sorted(f for f in os.listdir(PICTURES)
                   if f.startswith("radimg_") and f.endswith(".png"))
    # sizeable kaiju art and panels: the pictures a retheme redraws
    big = []
    for n in names:
        with Image.open(os.path.join(PICTURES, n)) as im:
            # (not the square credits photo: art, not people)
            if im.width >= 140 and im.height >= 100 and im.width != im.height:
                big.append(n)
    chosen, filler = big[:10], big[10:34]
    rels = []
    for n in chosen + filler:
        shutil.copy2(os.path.join(PICTURES, n),
                     os.path.join(project, "images", "scene_textures", n))
        rels.append("images/scene_textures/" + n)
    picks = {}
    for i, n in enumerate(chosen):
        with Image.open(os.path.join(PICTURES, n)) as im:
            im = im.convert("RGBA")
            # the modder's own master: black and white, twice the size
            grey = ImageOps.grayscale(im.convert("RGB"))
            bw = Image.merge("RGBA", (grey, grey, grey, im.split()[3]))
            master = bw.resize((im.width * 2, im.height * 2), Image.LANCZOS)
            own = os.path.join(mine, "Pictures", "BW %02d %s.png" % (
                i + 1, ("kaiju", "panel", "banner", "art")[i % 4]))
            master.save(own)
            # the card's copy: stretched back to the slot and squeezed into BC3
            made = np.asarray(master.resize(im.size, Image.LANCZOS))
            back = dds.decode_bc3(dds.encode_bc3(made), im.width, im.height)
            copy = os.path.join(old, "images", "scene_textures", n)
            Image.fromarray(back, "RGBA").save(copy)
            picks["images/scene_textures/" + n] = copy
    # the colour originals of three of them, which the search must pass over
    for n in chosen[:3]:
        shutil.copy2(os.path.join(PICTURES, n),
                     os.path.join(mine, "Pictures", "colour reference " + n[-12:]))
    return rels, picks


def _fixture(scratch):
    project = os.path.join(scratch, "GZ 1.16 Premium Extract Custom V2.0 Orchestral BW")
    old = os.path.join(scratch, "GZ 1.16 Premium V1.93 card extract")
    mine = os.path.join(scratch, "My Godzilla retheme files")
    for d in (os.path.join(project, "audio"),
              os.path.join(project, "images", "scene_textures"),
              os.path.join(old, "audio"), os.path.join(old, "images", "scene_textures"),
              os.path.join(mine, "Sounds"), os.path.join(mine, "Pictures")):
        os.makedirs(d, exist_ok=True)
    arels, apicks = _sounds(scratch, project, old, mine)
    irels, ipicks = _pictures(project, old, mine)
    _baseline(project, arels + irels)
    # the old extract: every card file in its baseline (that is what makes
    # its files copies off a card)
    _baseline(old, sorted(r for r in (list(apicks) + list(ipicks))))
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"audio": apicks, "image": ipicks}, f, indent=2)
    return project, mine


LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    global REPO
    REPO, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    tag = "after_" if after else "before_"
    os.makedirs(out_dir, exist_ok=True)
    print("repo:", REPO, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad443-")
    project, mine = _fixture(scratch)
    launcher = os.path.join(scratch, "launch443.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % REPO)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    webui_shot.REPO = REPO
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)

            def shot(ns, sub, name):
                api("ui.select_tab", ns)
                time.sleep(2)
                api(ns + ".scan")
                deadline = time.time() + 120
                while time.time() < deadline:
                    st = state().get(ns) or {}
                    if not st.get("scanning") and (st.get("rows") or st.get("total")):
                        break
                    time.sleep(0.5)
                time.sleep(4)                       # the change scan
                # the picks on show: every one a copy in the old extract
                api(ns + ".set_show", "Changed")
                time.sleep(1.5)
                try:
                    opened = api(ns + ".originals_open")
                except Exception as e:              # noqa: BLE001 - main has none
                    print(ns, "no originals window:", e, flush=True)
                    opened = False
                if opened:
                    api(ns + ".originals_set", "folder", os.path.join(mine, sub))
                    api(ns + ".originals_find")
                    deadline = time.time() + 300
                    while time.time() < deadline:
                        time.sleep(1)
                        o = (state().get(ns) or {}).get("originals") or {}
                        if not o.get("busy") and o.get("rows"):
                            break
                    o = (state().get(ns) or {}).get("originals") or {}
                    print(ns, "status:", o.get("status"), flush=True)
                    for r in o.get("rows") or []:
                        print("   %s | %s | %s | %s | %s" % (
                            r["name"], r["now"], r["file"], r["match"], r["note"]), flush=True)
                    time.sleep(2)
                page.mouse.move(1500, 20)
                time.sleep(0.8)
                page.screenshot(path=os.path.join(out_dir, tag + name))

            shot("audio", "Sounds", "audio_find_originals.png")
            api("audio.originals_close") if after else None
            shot("images", "Pictures", "images_find_originals.png")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
