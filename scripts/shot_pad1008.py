"""PAD-1008 proof shot: a jukebox song's play button sits next to the song, as the intro video's does.

    python scripts/shot_pad1008.py <repo> <out_dir> [--after]

The PAD-1000 rig (shot_pad1000: a scratch Stern project whose jukebox has 20 songs, most with an
intro video), with three sounds on shots in its sidecar too. Writes <before_|after_>audio_jukebox.png
(the Jukebox window) and <before_|after_>shots_window.png (the Sounds on shots window), and prints
which buttons each window's first row has in which cell.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1000 as J  # noqa: E402
import webui_shot  # noqa: E402


CELLS = """() => [...document.querySelectorAll('.modal .aud-juke tbody tr:first-child td')]
  .map((td) => [...td.querySelectorAll('button')].map((b) => b.getAttribute('aria-label')))"""


def _shots(project):
    """Three sounds on shots, the project's own sounds, in the sidecar beside the jukebox."""
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        d = json.load(f)
    shot = lambda m, mn, s, sn, n: {"mode": m, "mode_name": mn, "switch": s, "switch_name": sn,  # noqa: E731
                                    "file": os.path.join(project, "audio", "idx%04d.wav" % n)}
    d["sound_modes"] = {"names": [], "slots": {}, "shots": [
        shot(16, "Mode 16", 98, "Left ramp made", 3), shot(16, "Mode 16", 99, "Left orbit", 5),
        shot(17, "Mode 17", 98, "Left ramp made", 7)]}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    pre = "after_" if "--after" in sys.argv else "before_"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1008-")
    project = J._project(scratch)
    _shots(project)
    proc, url = J._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); "
                                 "localStorage.removeItem('pad.modal.jukebox'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            J._open(page, state)
            page.screenshot(path=os.path.join(out_dir, pre + "audio_jukebox.png"))
            print("jukebox first row cells:", page.evaluate(CELLS), flush=True)
            page.keyboard.press("Escape")
            time.sleep(0.8)
            page.locator("button:has-text('Sounds on shots')").first.click()
            page.wait_for_selector(".modal .aud-juke", timeout=20000)
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, pre + "shots_window.png"))
            print("shots first row cells:", page.evaluate(CELLS), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
