"""PAD-494 proof shots: one card, several sets of sounds, a MUSIC MODE on the machine picks the set.

    python scripts/shot_pad494.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Godzilla LE 1.16 project made from a stock audio extract (PAD494_EXTRACT,
default the Desktop's gzho: a dozen of its slots copied, its names files and extract record with
them). The Blue Oyster Cult "Godzilla" slot has a replacement (the modder's standard mix) and, in the
sidecar's ``sound_modes``, an orchestral mix for modes 2 and 4 (one file in two modes); the 1954 main
title has a mode 3 file only. Only mode 2 is named, so the others take the default names.
Writes, under the same names before and after:

- <before_|after_>audio_tab.png    the Audio tab on the Blue Oyster Cult slot
- <before_|after_>audio_menu.png   its right-click menu, "Music modes" opened where it is
- <before_|after_>audio_mode_level.png   mode 2's file played from that menu: the Replacement
  pane holds it, and the loudness box beside it (round 4: that file's own, +3 dB; before, the
  sound's own +2 dB, which also reached its mode files)

Before (main) the tab knows nothing of the modes the sidecar holds: one replacement per slot.
After (--after, the ticket branch) the rows carry their modes, and the menu has "Music modes".
(Round 3: before = v1.166.3, modes 2 and 3 only, unnamed modes called by number; after = four modes
offered, "Add a music mode..." up to eight, unnamed modes Standard / Custom A / Custom B...)

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
EXTRACT = os.environ.get("PAD494_EXTRACT", r"C:\Users\david\OneDrive\Desktop\gzho")
BOC = "idx2095 - music - Blue \u00d6yster Cult - Godzilla.wav"
MAIN_TITLE = "idx0974 - music - \u4f0a\u798f\u90e8\u662d - Godzilla Main Title (Godzilla 1954).wav"
SOUNDS = (BOC, MAIN_TITLE, "idx0000 - music.wav", "idx0004 - music.wav", "idx0066 - music.wav",
          "idx0084 - music.wav", "idx0095 - music.wav", "idx0179 - music.wav",
          "idx0002 - SE GZ FX TANK FIRE DOUBLE FAST 1.wav")
#: the modder's own files: (name, the stock sound standing in for it)
STANDARD = ("Godzilla - standard mix.wav", "idx0004 - music.wav")
ORCHESTRAL = ("Godzilla - orchestral.wav", "idx0066 - music.wav")
HEISEI = ("Main title - Heisei.wav", "idx0084 - music.wav")


def _project(scratch):
    dst = os.path.join(scratch, "gz_le_116")
    os.makedirs(os.path.join(dst, "audio"))
    shutil.copy2(os.path.join(EXTRACT, ".extract_source.json"), dst)
    lines = []
    for name in ("music_titles.csv", "sound_test_names.csv"):
        shutil.copy2(os.path.join(EXTRACT, name), os.path.join(dst, name))
    for name in SOUNDS:
        shutil.copy2(os.path.join(EXTRACT, "audio", name), os.path.join(dst, "audio", name))
        with open(os.path.join(dst, "audio", name), "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    mine = os.path.join(scratch, "Heisei music")
    os.makedirs(mine)
    own = {}
    for name, src in (STANDARD, ORCHESTRAL, HEISEI):
        own[name] = os.path.join(mine, name)
        shutil.copy2(os.path.join(EXTRACT, "audio", src), own[name])
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"audio": {"audio/" + BOC: own[STANDARD[0]]},
                   "audio_levels": {"audio/" + BOC: 2},
                   "sound_modes": {"names": ["", "Orchestral"],
                                   "levels": {"audio/" + BOC: {"2": 3}},
                                   "slots": {"audio/" + BOC: {"2": own[ORCHESTRAL[0]],
                                                              "4": own[ORCHESTRAL[0]]},
                                             "audio/" + MAIN_TITLE: {"3": own[HEISEI[0]]}}}},
                  f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch494.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait_scan(state, limit=180):
    deadline = time.time() + limit
    while time.time() < deadline:
        st = state().get("audio") or {}
        if st.get("rows") and not st.get("scanning"):
            return st
        time.sleep(1)
    return state().get("audio") or {}


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad494-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tag = "after_" if after else "before_"
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            st = _wait_scan(state)
            print("audio rows:", len(st.get("rows") or []), flush=True)
            print("status:", st.get("status"), flush=True)
            row = page.locator(".tr:has-text('Blue')").first
            row.click()
            time.sleep(3)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            time.sleep(0.5)
            page.screenshot(path=out("audio_tab.png"))
            row.click(button="right")
            time.sleep(1)
            item = page.locator(".menu .mi:has-text('Music modes')").first
            if item.count():
                item.hover()
                time.sleep(0.8)
            print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            page.screenshot(path=out("audio_menu.png"))
            page.keyboard.press("Escape")
            time.sleep(0.5)
            # mode 2's file in the Replacement pane, and the loudness box beside it
            api("audio.menu_action", "mode_play:2", "audio/" + BOC)
            time.sleep(2.5)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            api("audio.stop")
            time.sleep(0.8)
            st = state().get("audio") or {}
            print("pane:", (st.get("panes") or {}).get("rep", {}).get("name"),
                  "| box:", st.get("level_label") or "Loudness for this clip:", st.get("level"),
                  flush=True)
            page.screenshot(path=out("audio_mode_level.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
