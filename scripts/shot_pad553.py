"""PAD-553 proof shots: the Audio and Video tabs of a project extracted from a card the app built
with a music mode (Godzilla LE 1.16 "SE GZ MX TUNE 16", mode 2 "Orchestral") and random clips
(EndOfBallBonus_BackgroundLoop, two more clips).

    python scripts/shot_pad553.py <repo> <out_dir> <extract> [--after]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). <extract> is the extract of that card (c:/tmp/PAD-553/build_proof.py builds the
card, extract.py extracts it). The rig serves a hard-linked copy of its audio and video: with
--after, the project as the branch's extract left it (the read-back's record and its
"Music mode files"); without, as main's extract leaves it (no record). Writes, under the same name
before and after:

- audio.png  the Audio tab on TUNE 16 with its row selected and the More menu open
- video.png  the Video tab on EndOfBallBonus_BackgroundLoop with the More menu open

Needs Playwright (PAD_PWLIB or the user site-packages one) and the installed Edge.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

TUNE = "audio/idx2241 - SE GZ MX TUNE 16.wav"
CLIP = "video/EndOfBallBonus_BackgroundLoop.mov"


def _linked(src, dst, after):
    """*src*'s audio, video and records as hard links in *dst* (the media is not copied)."""
    keep = ["audio", "video"] + (["Music mode files"] if after else [])
    for top in keep:
        for dirpath, _dirs, files in os.walk(os.path.join(src, top)):
            rel = os.path.relpath(dirpath, src)
            os.makedirs(os.path.join(dst, rel), exist_ok=True)
            for name in files:
                os.link(os.path.join(dirpath, name), os.path.join(dst, rel, name))
    for name in (".extract_source.json", ".checksums.md5", "music_titles.csv",
                 "sound_test_names.csv") + ((".staged_changes.json",) if after else ()):
        if os.path.isfile(os.path.join(src, name)):
            shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
    if after:
        # the read-back's record points into the extract: point it at this copy
        side = os.path.join(dst, ".staged_changes.json")
        with open(side, encoding="utf-8") as f:
            text = f.read()
        with open(side, "w", encoding="utf-8") as f:
            f.write(text.replace(src.replace("\\", "\\\\"), dst.replace("\\", "\\\\")))
    return dst


def _more(page):
    page.locator('.pagehead [aria-label="More"]:visible').first.click()
    time.sleep(1.2)


def main():
    repo, out_dir, extract = (os.path.abspath(a) for a in sys.argv[1:4])
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad553-", dir=os.path.dirname(extract))
    project = _linked(extract, os.path.join(scratch, "gz_le_built"), after)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            base._wait_scan(state, "audio", limit=600)
            api("ui.set", "audio", "search", "TUNE 16")
            time.sleep(2)
            api("audio.select", [TUNE])
            time.sleep(2)
            print("audio row:", [r for r in (state().get("audio") or {}).get("rows", [])
                                 if r.get("k") == TUNE], flush=True)
            _more(page)
            page.screenshot(path=out("audio.png"))
            page.keyboard.press("Escape")
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video", limit=900)
            api("ui.set", "video", "search", "EndOfBallBonus")
            time.sleep(8)                   # the scan's own first-row pick lands first
            api("video.select", CLIP)
            time.sleep(5)
            print("video row:", [r for r in (state().get("video") or {}).get("rows", [])
                                 if r.get("rel") == CLIP], flush=True)
            _more(page)
            page.screenshot(path=out("video.png"))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))
    print("scratch", scratch)


if __name__ == "__main__":
    main()
