"""PAD-1084 proof shot: a sound's "Play in turn" menu adds several files at once and sets all their loudness.

    python scripts/shot_pad1084.py <repo> <out_dir> [--after]

Writes <before_|after_>audio_menu.png: the Audio tab on a scratch Godzilla Pro 1.16 project whose
idx0974 has a music mode 2 song with two more played at random, its right-click menu's "Play in turn"
opened. Before (main) each part offers "Add a sound to play in turn…" (one file per dialog) and a
loudness entry per file only; after, "Add sounds to play in turn…" (pick several) and "Loudness of all
N sounds…" (one entry for the mode's song and every song beside it).

Needs Playwright (the user site-packages one) and the installed Edge. The project is made in a
scratch folder (the capture server rewrites caches inside the project).
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
from shot_pad481 import _tone  # noqa: E402
from shot_pad565 import LAUNCHER, _wait_scan  # noqa: E402

CARD = os.environ.get("PAD1084_CARD", r"D:\Pinball\images\Stern\spike2"
                      r"\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
REL = "audio/idx0974 - music.wav"


def _project(scratch):
    import hashlib
    dst = os.path.join(scratch, "godzilla_pro_116")
    os.makedirs(os.path.join(dst, "audio"))
    mine = os.path.join(scratch, "jukebox")
    os.makedirs(mine)
    st = os.stat(CARD)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "size": st.st_size,
                   "mtime": int(st.st_mtime), "card_version": "1.16.0"}, f, indent=2)
    lines = []
    for hz, rel in ((440, REL), (660, "audio/idx0975 - music.wav")):
        path = os.path.join(dst, *rel.split("/"))
        _tone(path, hz)
        with open(path, "rb") as f:
            lines.append("%s\t%s\n" % (rel, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    songs = []
    for k, name in enumerate(("Theme A.wav", "Theme B.wav", "Theme C.wav")):
        p = os.path.join(mine, name)
        _tone(p, 300 + 100 * k)
        songs.append(p)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"sound_modes": {
            "names": ["Standard", "Jukebox"], "slots": {REL: {"2": songs[0]}}, "levels": {},
            "mode_turns": {REL: {"2": songs[1:]}}, "mode_random": {REL: ["2"]}}}, f, indent=2)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1084-")
    project = _project(scratch)
    launcher = os.path.join(scratch, "launch1084.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_menu.png")
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
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            st = _wait_scan(state)
            print("audio rows:", len(st.get("rows") or []), flush=True)
            row = page.locator(".tr:has-text('idx0974')").first
            row.click()
            time.sleep(1)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            time.sleep(25)              # the offer is read off the card in the background
            row.click(button="right")
            time.sleep(1)
            item = page.locator(".menu .mi:has-text('Play at random'), .menu .mi:has-text('Play in turn')").first
            if item.count():
                item.hover()
                time.sleep(0.8)
            print("menu:", ascii(page.locator(".menu .mi").all_inner_texts()), flush=True)
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
