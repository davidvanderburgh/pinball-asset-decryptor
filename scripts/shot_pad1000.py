"""PAD-1000 proof shot: the Jukebox window can be moved and resized, and keeps its place.

    python scripts/shot_pad1000.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project made from a stock extract (PAD1000_EXTRACT, default
C:\\tmp\\Pinball\\Deadpool Pro: a dozen of its sounds and clips), whose sidecar gives the jukebox 20
songs with long names, the way an owner's album rips are named. The jukebox is The Beatles' own, so the
launcher lets this title offer it (``_jukebox_why`` -> None): the window itself is what is shown. Writes:

- <before_|after_>audio_jukebox.png   the Audio tab with the Jukebox window open

Before (main) the window is fixed in the middle at 860 px, its list 52% of the page high, with both
scroll bars. After (--after) the shot drags the window's title bar to the left and its corner grip
wider and taller, reloads the page and opens the window again: it comes back where it was left, at
that size, and the list fills it with no scroll bars.

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

EXTRACT = os.environ.get("PAD1000_EXTRACT", r"C:\tmp\Pinball\Deadpool Pro")
SOUNDS = ["idx%04d.wav" % i for i in range(12)]
CLIPS = ("ATTRACT_LOOP1.mov", "ATTRACT_LOOP2.mov", "ATTRACT_LOOP3.mov")
SONGS = ("01 - Abbey Road (2019 Remaster) - Come Together", "02 - Abbey Road (2019 Remaster) - Something",
         "03 - Abbey Road (2019 Remaster) - Maxwell's Silver Hammer",
         "04 - Abbey Road (2019 Remaster) - Oh! Darling", "05 - Abbey Road (2019 Remaster) - Octopus's Garden",
         "06 - Abbey Road (2019 Remaster) - I Want You (She's So Heavy)",
         "07 - Abbey Road (2019 Remaster) - Here Comes The Sun", "08 - Abbey Road (2019 Remaster) - Because",
         "09 - Abbey Road (2019 Remaster) - You Never Give Me Your Money",
         "10 - Abbey Road (2019 Remaster) - Sun King", "11 - Abbey Road (2019 Remaster) - Mean Mr. Mustard",
         "12 - Abbey Road (2019 Remaster) - Polythene Pam",
         "13 - Abbey Road (2019 Remaster) - She Came In Through The Bathroom Window",
         "14 - Abbey Road (2019 Remaster) - Golden Slumbers", "15 - Abbey Road (2019 Remaster) - Carry That Weight",
         "16 - Abbey Road (2019 Remaster) - The End", "17 - Abbey Road (2019 Remaster) - Her Majesty",
         "01 - Let It Be (Remastered 2009) - Two Of Us", "02 - Let It Be (Remastered 2009) - Dig A Pony",
         "03 - Let It Be (Remastered 2009) - Across The Universe")
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui.tabs import audio as _A
_A.AudioTab._jukebox_why = lambda self: None      # this title stands in for The Beatles
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _project(scratch):
    dst = os.path.join(scratch, "deadpool_pro_116")
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
    for k, song in enumerate(SONGS):
        a = os.path.join(mine, song + ".wav")
        shutil.copy2(os.path.join(EXTRACT, "audio", SOUNDS[k % len(SOUNDS)]), a)
        g = {"audio": a, "weight": (3, 2, 2, 1)[k % 4]}
        if k % 3 != 2:
            g["video"] = os.path.join(mine, song + " - intro.mp4")
            shutil.copy2(os.path.join(EXTRACT, "video", CLIPS[k % len(CLIPS)]), g["video"])
        songs.append(g)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"jukebox": {"songs": songs}}, f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch1000.py")
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
    for _ in range(60):
        if (state().get("audio") or {}).get("jukebox"):
            break
        time.sleep(1)
    page.locator("button:has-text('Jukebox')").first.click()
    page.wait_for_selector(".modal .aud-juke", timeout=20000)
    time.sleep(1)


def _report(page, what):
    print(what, page.evaluate("""() => { const m = document.querySelector('.modal'), l = m.querySelector('.aud-juke');
      const r = m.getBoundingClientRect(), bd = m.querySelector('.bd');
      const sc = (e) => ({x: e.scrollWidth > e.clientWidth, y: e.scrollHeight > e.clientHeight});
      return {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
              list: sc(l), body: sc(bd)}; }"""), flush=True)


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1000-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
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
            _open(page, state)
            _report(page, "opened:")
            if after:
                hd = page.locator(".modal > .hd .h2").bounding_box()
                sx, sy = hd["x"] + 40, hd["y"] + hd["height"] / 2
                page.mouse.move(sx, sy)
                page.mouse.down()
                page.mouse.move(sx - 280, sy - 62, steps=12)
                page.mouse.up()
                _report(page, "moved:")
                g = page.locator(".modal > .modal-grip").bounding_box()
                page.mouse.move(g["x"] + g["width"] / 2, g["y"] + g["height"] / 2)
                page.mouse.down()
                page.mouse.move(g["x"] + g["width"] / 2 + 600, g["y"] + g["height"] / 2 + 140, steps=12)
                page.mouse.up()
                _report(page, "resized:")
                page.keyboard.press("Escape")
                time.sleep(1)
                page.reload()                                # the next session of the app
                page.wait_for_function("window.__padReady === true", timeout=60000)
                time.sleep(2)
                _open(page, state)
                _report(page, "reopened:")
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
