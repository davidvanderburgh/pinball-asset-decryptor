"""PAD-998 proof shot: the Jukebox window's ▶ while its song plays.

    python scripts/shot_pad998.py <repo> <out_dir> [--after]

Serves <repo> on a scratch The Beatles 1.29 project (an .extract_source.json naming the stock card, a
few generated WAVs as its sounds) whose sidecar gives the jukebox three songs (generated 30 s tones).
Opens the Jukebox window, presses ▶ on song 1 and, while it plays, writes:

- <before_|after_>jukebox_playing.png   the window with song 1 playing in the pane behind it
- <before_|after_>attract_flipper_sound.png   the Attract page's Flipper sounds with ▶ pressed on one

The Attract page reads the game's attract screens off its card, which the scratch project has none
of, so the launcher stands in two screens for them (``attract_items.project_pages``); the flipper
sound is the project's own record. Before, that ▶ sends the file to the Audio tab's Replacement pane,
which is not on the page, so nothing plays; after, it plays there and turns into ■.

Before (main) the button stays ▶ and nothing in the window stops the song. After (--after, the ticket
branch) it is ■ while the song plays; the rig then presses it and checks the page's audio stopped
(the <audio> elements' paused flags, read through a play/pause spy - the Edge window is muted).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import math
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.plugins.stern import attract_items as AI
AI.title_refusal = lambda prof: ""
AI.project_refusal = lambda folder, prof: ""
AI.project_pages = lambda folder, prof=None: [AI.Page(0, 1, 0, 6.0, "Logo"), AI.Page(1, 2, 0, 8.0, "High scores")]
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
SONGS = ("Across The Universe.wav", "All Together Now.wav", "Hey Jude.wav")
#: every <audio> the page makes, so the rig can tell whether one still plays
SPY = """
window.__auds = [];
const _play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  if (!window.__auds.includes(this)) window.__auds.push(this); return _play.apply(this, arguments); };
try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}
"""
PLAYING = "window.__auds.filter((a) => !a.paused).length"


def _tone(path, secs, hz):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / 22050)))
                               for i in range(int(secs * 22050))))


def _project(scratch):
    dst = os.path.join(scratch, "beatles_129")
    os.makedirs(os.path.join(dst, "audio"))
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_name": "beatles-1_29_0.Release.16G.sdcard.raw", "card_version": "1.29"}, f)
    for i in (42, 200, 311):
        _tone(os.path.join(dst, "audio", "idx%04d.wav" % i), 2, 300 + i)
    mine = os.path.join(scratch, "Let It Be sessions")
    os.makedirs(mine)
    songs = []
    for k, song in enumerate(SONGS):
        a = os.path.join(mine, song)
        _tone(a, 30, 220 * (k + 1))
        songs.append({"audio": a, "weight": 2})
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"jukebox": {"songs": songs},
                   "sound_modes": {"names": [], "slots": {}, "attract": [songs[2]["audio"]]}}, f, indent=2)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad998-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    S.LAUNCHER = LAUNCHER
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "jukebox_playing.png")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(SPY)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            for _ in range(60):
                if (state().get("audio") or {}).get("jukebox") is not None:
                    break
                time.sleep(1)
            print("jukebox:", (state().get("audio") or {}).get("jukebox"), flush=True)
            page.locator("button:has-text('Jukebox')").first.click()
            time.sleep(2)
            row = page.locator(".modal .aud-juke tbody tr").first
            row.locator("button").first.click()
            time.sleep(3)
            print("after ▶: playing", page.evaluate(PLAYING), "| button title:",
                  row.locator("button").first.get_attribute("title"), flush=True)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            # press the same button again: before it plays the song from the top, after it stops it
            row.locator("button").first.click()
            time.sleep(2)
            print("after a 2nd press: playing", page.evaluate(PLAYING), "| button title:",
                  row.locator("button").first.get_attribute("title"), flush=True)
            # ▶ again, then Close: the song is the pane's now and plays on, as any pane's does
            row.locator("button").first.click()
            time.sleep(2)
            print("▶ again: playing", page.evaluate(PLAYING), flush=True)
            page.locator(".modal button:has-text('Close')").click()
            time.sleep(1)
            api("ui.select_tab", "attract")
            item = page.locator(".at-item").first
            item.wait_for(timeout=60000)
            time.sleep(1)
            print("Attract: playing before ▶", page.evaluate(PLAYING), flush=True)
            item.locator("button").first.click()
            time.sleep(3)
            print("Attract after ▶: playing", page.evaluate(PLAYING), flush=True)
            item.scroll_into_view_if_needed()
            page.screenshot(path=os.path.join(out_dir, ("after_" if after else "before_") + "attract_flipper_sound.png"))
            item.locator("button").first.click()
            time.sleep(2)
            print("Attract after a 2nd press: playing", page.evaluate(PLAYING), flush=True)
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
