"""PAD-1007 proof shot: the Jukebox's pools - the song modes, the special modes and the background music
each draw from their own songs.

    python scripts/shot_pad1007.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Beatles 1.29 project made from a stock extract (PAD1007_EXTRACT, default
C:\\tmp\\PAD-1007\\proj: its .extract_source.json names the card, so the app knows the title and its pools,
and a dozen of its sounds), whose sidecar gives the jukebox ten songs: six for the song modes, two for the
special modes, two for the background music (``"pool"`` on each). Writes:

- <before_|after_>audio_jukebox.png           the Jukebox window as it opens
- <before_|after_>audio_jukebox_special.png   after (--after) picking Special modes in it

Before (main) the window has one list: every song, whatever its pool, goes to the five song modes. After
it opens on Song modes (its six songs) with a picker of the three pools, and Special modes shows its two.

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

EXTRACT = os.environ.get("PAD1007_EXTRACT", r"C:\tmp\PAD-1007\proj")
SOUNDS = ["idx%04d.wav" % i for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 667)]
CLIP = "FeatureStarts_POP_Start.mov"
SONGS = (("songs", "Come Together"), ("songs", "Something"), ("songs", "Here Comes The Sun"),
         ("songs", "Two Of Us"), ("songs", "Across The Universe"), ("songs", "Get Back"),
         ("special", "Twist And Shout"), ("special", "Help!"),
         ("background", "Yellow Submarine"), ("background", "Octopus's Garden"))


def _project(scratch):
    dst = os.path.join(scratch, "beatles_129")
    os.makedirs(os.path.join(dst, "audio"))
    shutil.copy2(os.path.join(EXTRACT, ".extract_source.json"), dst)
    lines = []
    for name in SOUNDS:
        shutil.copy2(os.path.join(EXTRACT, "audio", name), os.path.join(dst, "audio", name))
        with open(os.path.join(dst, "audio", name), "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    mine = os.path.join(scratch, "My Beatles rips")
    os.makedirs(mine)
    songs = []
    for k, (pool, song) in enumerate(SONGS):
        a = os.path.join(mine, song + ".wav")
        shutil.copy2(os.path.join(EXTRACT, "audio", SOUNDS[k % 12]), a)
        g = {"audio": a, "weight": (3, 2, 2, 1)[k % 4]}
        if pool != "songs":
            g["pool"] = pool
        if pool == "songs" and k % 3 != 2:
            g["video"] = os.path.join(mine, song + ".mp4")
            shutil.copy2(os.path.join(EXTRACT, "video", CLIP), g["video"])
        songs.append(g)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"jukebox": {"songs": songs}}, f, indent=2)
    return dst


LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch1007.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                   extra_env={"PYTHONPATH": site.getusersitepackages()})


def _open(page, state):
    S._wait_scan(state)
    for _ in range(90):
        if (state().get("audio") or {}).get("jukebox"):
            break
        time.sleep(1)
    print("jukebox button:", (state().get("audio") or {}).get("jukebox"), flush=True)
    page.locator("button:has-text('Jukebox')").first.click()
    page.wait_for_selector(".modal .aud-juke", timeout=20000)
    time.sleep(1)


def _rows(page):
    return page.evaluate("""() => [...document.querySelectorAll('.modal .aud-juke tbody tr')]
      .map((r) => r.cells[0].textContent + ' ' + r.cells[1].textContent)""")


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1007-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
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
            _open(page, state)
            page.mouse.move(5, 890)
            time.sleep(0.5)
            print("opened:", _rows(page), flush=True)
            page.screenshot(path=os.path.join(out_dir, tag + "audio_jukebox.png"))
            if after:
                page.locator(".modal .aud-juke-pools button:has-text('Special modes')").click()
                time.sleep(1)
                page.mouse.move(5, 890)
                time.sleep(0.5)
                print("special:", _rows(page), flush=True)
            page.screenshot(path=os.path.join(out_dir, tag + "audio_jukebox_special.png"))
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
