"""PAD-641 proof shot: the Audio tab's sounds for the flipper buttons in attract mode.

    python scripts/shot_pad641.py <repo> <out_dir> [--after]

Serves <repo> on a scratch James Bond 007 LE 1.06 project made from a stock audio extract
(PAD641_EXTRACT, default C:\\tmp\\PAD-641\\bondle_x: a dozen of its sounds copied with its names
file and extract record), whose sidecar gives the flipper buttons three sounds in attract (three of
the game's own callouts, saved under names a modder would give them). Writes, under the same name
before and after:

- <before_|after_>audio_attract.png   the Audio tab; after, with the Attract flipper sounds menu open

Before (main) the tab has no such control: the game's flipper buttons cannot be given sounds in
attract. After (--after, the ticket branch) the page header has "Attract flipper sounds (3)", and
its menu adds a sound, plays each one or takes it off.

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
import shot_pad494 as S  # noqa: E402
import webui_shot  # noqa: E402

EXTRACT = os.environ.get("PAD641_EXTRACT", r"C:\tmp\PAD-641\bondle_x")
SOUNDS = ["idx%04d.wav" % i for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 46)]
#: the modder's own files: (name, the stock sound standing in for it)
OWN = (("Shaken, not stirred.wav", "idx0003.wav"), ("The name's Bond.wav", "idx0005.wav"),
       ("Q - Pay attention, 007.wav", "idx0007.wav"))


def _project(scratch):
    dst = os.path.join(scratch, "bond_le_106")
    os.makedirs(os.path.join(dst, "audio"))
    shutil.copy2(os.path.join(EXTRACT, ".extract_source.json"), dst)
    for name in ("sound_test_names.csv", "sound_requests.tsv"):
        if os.path.isfile(os.path.join(EXTRACT, name)):
            shutil.copy2(os.path.join(EXTRACT, name), os.path.join(dst, name))
    lines = []
    for name in SOUNDS:
        shutil.copy2(os.path.join(EXTRACT, "audio", name), os.path.join(dst, "audio", name))
        with open(os.path.join(dst, "audio", name), "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    mine = os.path.join(scratch, "Bond callouts")
    os.makedirs(mine)
    own = []
    for name, src in OWN:
        own.append(os.path.join(mine, name))
        shutil.copy2(os.path.join(EXTRACT, "audio", src), own[-1])
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"sound_modes": {"names": [], "slots": {}, "attract": own, "attract_gap": 30}}, f, indent=2)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad641-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + os.environ.get("PAD641_SHOT", "audio_attract")
                       + ".png")
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
            st = S._wait_scan(state)
            for _ in range(60):                  # the plugin's offer comes with the scan
                st = state().get("audio") or {}
                if st.get("attract") is not None or not after:
                    break
                time.sleep(1)
            print("audio rows:", len(st.get("rows") or []), "| attract:", st.get("attract"), flush=True)
            page.locator(".tr").first.click()
            time.sleep(2)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            btn = page.locator("button:has-text('Attract flipper sounds')").first
            if btn.count():
                btn.click()
                time.sleep(1)
                print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
                gap = page.locator(".menu .mi:has-text('Time between sounds')").first
                if gap.count():                  # round 2: the time between two, its submenu open
                    gap.hover()
                    time.sleep(1)
                    print("menu now:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            else:
                print("no Attract flipper sounds button", flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
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
