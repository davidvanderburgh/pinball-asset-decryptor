"""PAD-820 proof shot: Deadpool's songs on the Audio tab, named from the game's Sound Test.

    python scripts/shot_pad820.py <repo> <audio_dir> <out_dir> [--after]

Serves <repo> on a scratch Deadpool Pro 1.16 project whose ``audio/`` holds the
music-bank songs in <audio_dir> (``music_catNN_MMMM*.wav``, hard-linked, as a
music-bank extract of that checkout wrote them), opens the Audio tab and shoots
it from the image-sc16 bank on. Writes <before_|after_>audio_songs.png.

Before (main) every song is a bare ``music_catNN_MMMM``. After (--after, the
ticket branch) the 33 song files the Sound Test names carry those names.

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

CARD = r"D:\Pinball\images\Stern\spike2\deadpool_pro-1_16_0.Release.8G.sdcard.raw"


def _project(scratch, src):
    dst = os.path.join(scratch, "deadpool_pro_116")
    os.makedirs(os.path.join(dst, "audio"))
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "size": os.path.getsize(CARD), "mtime": int(os.path.getmtime(CARD)),
                   "card_version": "1.16.0"}, f)
    lines = []
    for name in sorted(os.listdir(src)):
        if not name.lower().endswith(".wav"):
            continue
        to = os.path.join(dst, "audio", name)
        try:
            os.link(os.path.join(src, name), to)
        except OSError:
            shutil.copy2(os.path.join(src, name), to)
        with open(to, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    return dst


def main():
    repo, src, out_dir = (os.path.abspath(a) for a in sys.argv[1:4])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad820-", dir=r"C:\tmp")
    project = _project(scratch, src)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_songs.png")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
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
            print("audio rows:", len(st.get("rows") or []), flush=True)
            # the list is virtual: scroll its scroller to the image-sc16 bank's first song
            at = next((i for i, r in enumerate(st.get("rows") or [])
                       if "music_cat16_0000" in json.dumps(r)), 0)
            page.evaluate("(y) => { const s = [...document.querySelectorAll('.tbl .scroller')]"
                          ".sort((a, b) => b.scrollHeight - a.scrollHeight)[0];"
                          " if (s) s.scrollTop = y; }", at * 32)
            time.sleep(1.5)
            print("scrolled to row", at, "|", page.locator(".tbl .tr:not(.th)").first.inner_text()[:80],
                  flush=True)
            page.screenshot(path=out)
            print("wrote", out, "| page errors:", errors, flush=True)
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
