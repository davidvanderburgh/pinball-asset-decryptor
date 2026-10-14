"""PAD-481 proof shots: Avengers: Infinity Quest Pro 1.10's sounds can play files in turn.

    python scripts/shot_pad481.py <repo> <out_dir> [--after]

Writes <before_|after_>audio_menu.png: the Audio tab on an Avengers Pro 1.10 project, a sound's
right-click menu with "Play in turn" opened. Before (main) its sound bank could not be rewritten,
so the submenu only had "Why not this sound?"; after, it offers "Add a sound to play in turn".

Serves <repo> on a scratch project made from the stock card (PAD481_CARD) with two short tones as
its "extracted" sounds, as scripts/shot_pad565.py does. Needs Playwright and the installed Edge.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
from shot_pad565 import LAUNCHER, _wait_scan  # noqa: E402

CARD = os.environ.get("PAD481_CARD", r"D:\Pinball\images\Stern\spike2"
                      r"\avengers_infinity_pro-1_10_0.Release.8G.sdcard.raw")
SOUNDS = ("idx0473 - sfx.wav", "idx0151 - sfx.wav")


def _tone(path, hz):
    import math
    frames = b"".join(int(8000 * math.sin(2 * math.pi * hz * i / 44100)).to_bytes(2, "little", signed=True)
                      for i in range(44100 // 2))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(frames)


def _project(scratch):
    dst = os.path.join(scratch, "avengers_pro_110")
    os.makedirs(os.path.join(dst, "audio"))
    st = os.stat(CARD)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "size": st.st_size,
                   "mtime": int(st.st_mtime), "card_version": "1.10.0"}, f, indent=2)
    lines = []
    for hz, name in zip((500, 1000), SOUNDS):
        path = os.path.join(dst, "audio", name)
        _tone(path, hz)
        with open(path, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch481.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad481-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_menu.png")
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
            st = _wait_scan(state)
            print("audio rows:", len(st.get("rows") or []), flush=True)
            row = page.locator(".tr:has-text('idx0473')").first
            row.click()
            time.sleep(1)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            # the offer is read off the card in the background: wait for it before the menu
            time.sleep(25)
            row.click(button="right")
            time.sleep(1)
            item = page.locator(".menu .mi:has-text('Play in turn')").first
            if item.count():
                item.hover()
                time.sleep(0.8)
            print("menu:", ascii(page.locator(".menu .mi").all_inner_texts()), flush=True)
            page.screenshot(path=out)
            print("page errors:", errors, flush=True)
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
