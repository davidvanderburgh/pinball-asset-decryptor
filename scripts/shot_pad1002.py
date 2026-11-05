"""PAD-1002 proof shot: the Jukebox window's Clear all… to start the song list over.

    python scripts/shot_pad1002.py <repo> <out_dir> [--after]

Serves <repo> on a scratch The Beatles 1.29 project whose jukebox already has four songs, opens the
Jukebox window and writes, under the same name before and after:

- <before_|after_>jukebox_window.png   the window with its four songs (after: with Clear all… in the footer)
- <before_|after_>jukebox_cleared.png  after: Clear all… asked and answered Yes, the list empty;
                                       before: the window as it is (there is no way to clear it at once)

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import shot_pad999 as P  # noqa: E402
import webui_shot  # noqa: E402


def _project(scratch):
    dst, _picked = P._project(scratch)
    mine = os.path.join(scratch, "My songs")
    songs = []
    for i, name in enumerate(("Hey Jude", "Revolution", "Get Back", "Let It Be")):
        P._wav(os.path.join(mine, name + ".wav"))
        songs.append({"audio": os.path.join(mine, name + ".wav"), "weight": 1 + i % 3})
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"jukebox": {"songs": songs}}, f)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    pre = "after_" if "--after" in sys.argv else "before_"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1002-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
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
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            for _ in range(60):
                if (state().get("audio") or {}).get("jukebox") is not None:
                    break
                time.sleep(1)
            page.locator("button:has-text('Jukebox')").first.click()
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, pre + "jukebox_window.png"))
            clear = page.locator(".modal button:has-text('Clear all')")
            if clear.count():
                clear.first.click()
                time.sleep(1.5)
                print("asked:", page.locator(".modal").last.inner_text()[:300], flush=True)
                page.locator(".modal button:has-text('Yes')").last.click()
                time.sleep(2)
            print("window:", page.locator(".modal").first.inner_text()[:400], flush=True)
            page.screenshot(path=os.path.join(out_dir, pre + "jukebox_cleared.png"))
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
