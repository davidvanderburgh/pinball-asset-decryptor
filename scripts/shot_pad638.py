"""PAD-638 proof shots: a sound's files in turn play AT RANDOM (scripts/shot_pad565.py's rig).

    python scripts/shot_pad638.py <repo> <out_dir> [--after]

The project's record says the tank-fire sound's three files play at random (``sound_modes``
``random``). Before (main) the app knows nothing of it: the menu offers files in turn only. After,
"Play at random (3 sounds)" with One after another / At random, At random ticked; round 2 adds each file's own loudness (sound 3 at -4 dB); round 3 a part per music mode
(mode 2's file with two sounds of its own, at random).

The tank-fire sound (idx 2) has a replacement and, in the sidecar's ``sound_modes`` ``turns``, two
more files the game plays in turn with it. Writes <before_|after_>audio_tab.png (the Audio tab on
that slot) and <before_|after_>audio_menu.png (its right-click menu, "Play in turn" opened where
it is). Before (main) the tab knows nothing of the turns: one replacement per slot.

Serves <repo> on a scratch Godzilla LE 1.16 project made from a stock audio extract (PAD494_EXTRACT,
default the Desktop's gzho), as shot_pad494.py does.

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
TANK = "idx0002 - SE GZ FX TANK FIRE DOUBLE FAST 1.wav"
#: the modder's own tank shots: the replacement, then the two played in turn with it
TANK_FILES = (("Tank shot A.wav", TANK), ("Tank shot B.wav", TANK), ("Tank shot C.wav", TANK))


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
    for name, src in TANK_FILES:
        own[name] = os.path.join(mine, name)
        shutil.copy2(os.path.join(EXTRACT, "audio", src), own[name])
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"audio": {"audio/" + TANK: own[TANK_FILES[0][0]]},
                   "sound_modes": {"turns": {"audio/" + TANK: [own[TANK_FILES[1][0]],
                                                               own[TANK_FILES[2][0]]]},
                                   "random": ["audio/" + TANK],
                                   "turn_levels": {"audio/" + TANK: {"3": -4}},
                                   # round 3: music mode 2's file, with two of its own at random
                                   "slots": {"audio/" + TANK: {"2": own[ORCHESTRAL[0]]}},
                                   "levels": {},
                                   "mode_turns": {"audio/" + TANK: {"2": [own[HEISEI[0]],
                                                                          own[STANDARD[0]]]}},
                                   "mode_random": {"audio/" + TANK: ["2"]}}},
                  f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch638.py")
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
    scratch = tempfile.mkdtemp(prefix="pad638-")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
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
            row = page.locator(".tr:has-text('TANK FIRE')").first
            row.click()
            time.sleep(3)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            time.sleep(0.5)
            page.screenshot(path=out("audio_tab.png"))
            row.click(button="right")
            time.sleep(1)
            item = page.locator(".menu .mi:has-text('(3 sounds)')").first
            if item.count():
                item.hover()
                time.sleep(0.8)
            print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            page.screenshot(path=out("audio_menu.png"))
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
