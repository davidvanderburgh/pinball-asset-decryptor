"""PAD-1074 proof shot: a row's own play button while its sound plays.

    python scripts/shot_pad1074.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project made here (four 20 s tones named
like jukebox songs), clicks the second row's play button and photographs
the list while it plays, then clicks that row's button again.  Writes
<before_|after_>audio_row_play.png and prints every row button's label at
each step (the label is what the button shows: Play or Stop), and whether
the Original pane was still playing after the second click.

Needs Playwright (the user site-packages one) and the installed Edge.  The
browser is muted.
"""
import hashlib
import os
import struct
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import webui_shot  # noqa: E402

SOUNDS = ("00m20s000 - idx0200 - Drive My Car.wav",
          "00m20s000 - idx0722 - Ticket To Ride.wav",
          "00m20s000 - idx0148 - Help!.wav",
          "00m20s000 - idx0431 - Taxman.wav")


def _wav(path, period):
    n = 20 * 22050
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", 3000 if i % period < period // 2 else -3000)
                               for i in range(n)))


def _project(scratch):
    dst = os.path.join(scratch, "beatles")
    os.makedirs(os.path.join(dst, "audio"))
    lines = []
    for i, name in enumerate(SOUNDS):
        p = os.path.join(dst, "audio", name)
        _wav(p, 30 + 10 * i)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    return dst


def _labels(page):
    return page.eval_on_selector_all(
        ".aud-rowplay", "els => els.map(e => e.getAttribute('aria-label'))")


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1074-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio",
                                        "--autoplay-policy=no-user-gesture-required"])
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
            time.sleep(2)
            print("idle:", _labels(page), flush=True)

            page.locator(".aud-rowplay").nth(1).click()
            time.sleep(2.5)
            print("playing row 2:", _labels(page), flush=True)
            page.mouse.move(5, 5)          # no hover highlight in the shot
            time.sleep(0.5)
            page.screenshot(path=out("audio_row_play.png"))
            print("shot", out("audio_row_play.png"), flush=True)

            page.locator(".aud-rowplay").nth(1).click()
            time.sleep(1.5)
            print("second click:", _labels(page), flush=True)
            print("pane buttons:", page.eval_on_selector_all(
                ".aud-transport button", "els => els.map(e => e.textContent.trim() || e.getAttribute('aria-label'))"),
                flush=True)
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
