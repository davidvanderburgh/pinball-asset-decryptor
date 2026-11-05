"""PAD-999 proof shot: the Jukebox's Add songs… with songs' audio and intro videos picked together.

    python scripts/shot_pad999.py <repo> <out_dir> [--after]

Serves <repo> on a scratch The Beatles 1.29 project (its extract record names the stock card; a few
short sounds) whose jukebox already has Get Back (Common, from an older folder) and Dig It. Add songs…
is then answered (``agent.use_files``) with a folder's Hey Jude and Revolution (each a .wav and an
.mp4), Get Back.wav again, and Let It Be.mp4 with no audio of its name. Writes, under the same name
before and after:

- <before_|after_>jukebox_add.png   the Jukebox window after the add (and its warning, if any)

Before (main) every picked file became a song, the videos too, and Get Back came in twice. After, the
videos are the intros of the songs of their names, Get Back takes the old one's place, and a warning
says so and that Let It Be.mp4 was left out.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import webui_shot  # noqa: E402


def _wav(path, seconds=1.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\0\0" * int(22050 * seconds))


def _project(scratch):
    dst = os.path.join(scratch, "beatles_129")
    lines = []
    for i in (42, 200, 419, 848):
        rel = "audio/idx%04d.wav" % i
        _wav(os.path.join(dst, *rel.split("/")))
        with open(os.path.join(dst, *rel.split("/")), "rb") as f:
            lines.append("%s\t%s\n" % (rel, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": r"D:\cards\beatles-1_29_0.img", "stock": {"sidx": "beatles-1_29_0.sidx"}}, f)
    old = os.path.join(scratch, "Older songs")
    _wav(os.path.join(old, "Get Back.wav"))
    _wav(os.path.join(old, "Dig It.wav"))
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"jukebox": {"songs": [{"audio": os.path.join(old, "Get Back.wav"), "weight": 3},
                                         {"audio": os.path.join(old, "Dig It.wav"), "weight": 2}]}}, f)
    mine = os.path.join(scratch, "Let It Be sessions")
    picked = []
    for name in ("Hey Jude", "Revolution"):
        _wav(os.path.join(mine, name + ".wav"))
        with open(os.path.join(mine, name + ".mp4"), "wb") as f:
            f.write(b"\0" * 64)
        picked += [os.path.join(mine, name + ".wav"), os.path.join(mine, name + ".mp4")]
    _wav(os.path.join(mine, "Get Back.wav"))
    with open(os.path.join(mine, "Let It Be.mp4"), "wb") as f:
        f.write(b"\0" * 64)
    picked += [os.path.join(mine, "Get Back.wav"), os.path.join(mine, "Let It Be.mp4")]
    return dst, picked


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad999-")
    project, picked = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "jukebox_add.png")
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
            S._wait_scan(state)
            for _ in range(60):                  # the plugin's offer comes with the scan
                if (state().get("audio") or {}).get("jukebox") is not None:
                    break
                time.sleep(1)
            page.locator("button:has-text('Jukebox')").first.click()
            time.sleep(2)
            api("agent.use_files", picked)
            page.locator(".modal button:has-text('Add songs')").first.click()
            time.sleep(3)
            print("window:", page.locator(".modal .aud-juke tr").all_inner_texts(), flush=True)
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
