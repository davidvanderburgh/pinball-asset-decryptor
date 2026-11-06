"""PAD-1018 proof shot: the Jukebox takes 256 songs in all, not 128.

    python scripts/shot_pad1018.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Beatles 1.29 project (shot_pad1007's: PAD1007_EXTRACT, default
C:\\tmp\\PAD-1007\\proj) whose jukebox has 128 songs, 43 + 43 + 42 over the three pools: the reporter's
case, a third pool that cannot get its 43rd song. Writes <before_|after_>audio_jukebox_full.png, the
Jukebox window open on Background music.

Before (main) Add songs is greyed out (128 is the most); after it can still be pressed, and the
window says how many songs it has of the most it takes (256).
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1007 as P  # noqa: E402
import webui_shot  # noqa: E402

POOLS = (("songs", 43), ("special", 43), ("background", 42))


def _project(scratch):
    dst = P._project(scratch)
    mine = os.path.join(scratch, "My Beatles rips")
    songs = []
    for pool, n in POOLS:
        for i in range(1, n + 1):
            a = os.path.join(mine, "%s %02d.wav" % (pool.title(), i))
            shutil.copy2(os.path.join(P.EXTRACT, "audio", P.SOUNDS[i % 12]), a)
            g = {"audio": a, "weight": 2}
            if pool != "songs":
                g["pool"] = pool
            songs.append(g)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"jukebox": {"songs": songs}}, f, indent=2)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1018-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = P._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tag = "after_" if after else "before_"
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
            P._open(page, state)
            page.locator(".modal .aud-juke-pools button:has-text('Background music')").click()
            time.sleep(1)
            page.mouse.move(5, 890)
            time.sleep(0.5)
            add = page.locator(".modal button:has-text('Add songs')").first
            print("add songs disabled:", add.is_disabled(), "title:", add.get_attribute("title"), flush=True)
            page.screenshot(path=os.path.join(out_dir, tag + "audio_jukebox_full.png"))
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
