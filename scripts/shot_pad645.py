"""PAD-645 proof shot: the Audio tab's sounds for the flipper buttons in attract mode on a game
PAD-641 left out (Deadpool LE 1.14: its port had no switch drain).

    python scripts/shot_pad645.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Deadpool LE 1.14 project (PAD645_PROJECT, default
C:\\tmp\\PAD-645\\b\\deadpool_le-1.14\\project: the sweep's one-sound project with its extract record),
whose sidecar gives the flipper buttons three sounds in attract. Writes, under the same name before
and after:

- <before_|after_>audio_attract.png   the Audio tab with the Attract flipper sounds menu open

Before (main) the menu says the game cannot have them; after (--after, the ticket branch) it lists
the three sounds and offers more.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
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

PROJECT = os.environ.get("PAD645_PROJECT", r"C:\tmp\PAD-645\b\deadpool_le-1.14\project")
#: the modder's own files, the sweep's tones standing in for them
OWN = (("Maximum effort.wav", "Flip A 500.wav"), ("Chimichangas.wav", "Flip B 1000.wav"),
       ("Fourth wall.wav", "Flip C 2000.wav"))


def _project(scratch):
    dst = os.path.join(scratch, "deadpool_le_114")
    shutil.copytree(PROJECT, dst)
    mine = os.path.join(scratch, "Deadpool callouts")
    os.makedirs(mine)
    own = []
    for name, src in OWN:
        own.append(os.path.join(mine, name))
        shutil.copy2(os.path.join(os.path.dirname(PROJECT), src), own[-1])
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"sound_modes": {"names": [], "slots": {}, "attract": own}}, f, indent=2)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad645-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_attract.png")
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
                if st.get("attract") is not None:
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
