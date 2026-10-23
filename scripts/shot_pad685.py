"""PAD-685 proof shot: the Audio tab's Jukebox for The Beatles' song modes.

    python scripts/shot_pad685.py <repo> <out_dir> [--after]

Serves <repo> on a scratch The Beatles 1.29 project made from a stock extract (PAD685_EXTRACT, default
C:\\tmp\\PAD-685\\proj: a dozen of its sounds, the five song modes' among them, copied with its names files
and extract record), whose sidecar gives the jukebox five songs (stock songs and intro clips of the game,
saved under names a modder would give them), one of them Rare and one Common. Writes, under the same name
before and after:

- <before_|after_>audio_jukebox.png   the Audio tab; after, with the Jukebox window open

Before (main) the tab has no jukebox: each song mode plays its own song. After (--after, the ticket
branch) the page header has "Jukebox (5)", and its window lists the songs, each with its intro video and
how often it comes up.

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

EXTRACT = os.environ.get("PAD685_EXTRACT", r"C:\tmp\PAD-685\proj")
SOUNDS = ["idx%04d.wav" % i for i in (42, 200, 311, 417, 419, 431, 494, 667, 669, 753, 797, 848)]
#: the modder's own songs: (song, the stock sound standing in for it, its intro, the stock clip, weight)
OWN = (("Hey Jude.wav", "idx0797.wav", "Hey Jude intro.mp4", "Taxman_Start.mov", 3),
       ("Revolution.wav", "idx0494.wav", "Revolution intro.mp4", "GameOver.mov", 2),
       ("Get Back.wav", "idx0311.wav", "Get Back intro.mp4", "Game_Start2.mov", 2),
       ("Don't Let Me Down.wav", "idx0848.wav", "Don't Let Me Down intro.mp4", "Game_Start1.mov", 2),
       ("Dig It.wav", "idx0669.wav", "", "", 1))


def _project(scratch):
    dst = os.path.join(scratch, "beatles_129")
    os.makedirs(os.path.join(dst, "audio"))
    os.makedirs(os.path.join(dst, "video"))
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
    mine = os.path.join(scratch, "Let It Be sessions")
    os.makedirs(mine)
    songs = []
    for song, src, intro, clip, weight in OWN:
        a = os.path.join(mine, song)
        shutil.copy2(os.path.join(EXTRACT, "audio", src), a)
        g = {"audio": a, "weight": weight}
        if intro:
            g["video"] = os.path.join(mine, intro)
            shutil.copy2(os.path.join(EXTRACT, "video", clip), g["video"])
        songs.append(g)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"jukebox": {"songs": songs}}, f, indent=2)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad685-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_jukebox.png")
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
                if st.get("jukebox") is not None or not after:
                    break
                time.sleep(1)
            print("audio rows:", len(st.get("rows") or []), "| jukebox:", st.get("jukebox"), flush=True)
            btn = page.locator("button:has-text('Jukebox')").first
            if btn.count():
                btn.click()
                time.sleep(2)
                print("window:", page.locator(".modal .aud-juke tr").all_inner_texts(), flush=True)
            else:
                print("no Jukebox button", flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
