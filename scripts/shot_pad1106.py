"""PAD-1106 proof shot: a song mode's music row plays a jukebox song in the Replacement pane.

    python scripts/shot_pad1106.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Beatles 1.29 project: its ``.extract_source.json`` names the stock card
(PAD1106_CARD, default D:\\Pinball\\images\\Stern\\spike2\\beatles-1_29_0.Release.8G.sdcard.raw), so the app
knows the title and its jukebox pools; its audio is a few synthetic tones named like the card's song-mode
records (idx0200 Drive My Car and so on), and its sidecar gives the jukebox six songs (four song modes, one
special, one background). Selects Drive My Car (idx0200) with Music shown and presses the Replacement
pane's Play. Writes <before_|after_>audio_jukebox_row.png.

Before (main) the pane says "no replacement assigned" and Play does nothing. After the row's cell says the
jukebox plays it, the pane holds one of the song modes' songs drawn at random, and it plays; the script
then presses Stop and Play again and logs the next draw.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
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

CARD = os.environ.get("PAD1106_CARD", r"D:\Pinball\images\Stern\spike2\beatles-1_29_0.Release.8G.sdcard.raw")
RECORDS = ((200, "Drive My Car"), (417, "Drive My Car (Loop Mania)"), (722, "Ticket To Ride"),
           (431, "Ticket To Ride (Super Spinners)"), (148, "Help!"), (848, "All My Loving (2 Ball MB)"),
           (370, "Taxman (Background)"), (5, "Coin"), (6, "Flipper"))
SONGS = (("songs", "Come Together", 3), ("songs", "Something", 2), ("songs", "Here Comes The Sun", 2),
         ("songs", "Get Back", 1), ("special", "Twist And Shout", 2), ("background", "Yellow Submarine", 2))


def _tone(path, hz, secs):
    rate = 22050
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / rate)))
                               for i in range(int(rate * secs))))


def _project(scratch):
    dst = os.path.join(scratch, "Beatles Jukebox")
    os.makedirs(os.path.join(dst, "audio"))
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    lines = []
    for n, (idx, name) in enumerate(RECORDS):
        f = "idx%04d - %s.wav" % (idx, name)
        _tone(os.path.join(dst, "audio", f), 220 + 40 * n, 3 + n % 4)
        with open(os.path.join(dst, "audio", f), "rb") as fh:
            lines.append("audio/%s\t%s\n" % (f, hashlib.md5(fh.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    mine = os.path.join(scratch, "My Beatles rips")
    os.makedirs(mine)
    songs = []
    for n, (pool, song, weight) in enumerate(SONGS):
        a = os.path.join(mine, song + ".wav")
        _tone(a, 500 + 70 * n, 6 + n)
        g = {"audio": a, "weight": weight}
        if pool != "songs":
            g["pool"] = pool
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
    launcher = os.path.join(scratch, "launch1106.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                   extra_env={"PYTHONPATH": site.getusersitepackages()})


def _rep(state):
    return ((state().get("audio") or {}).get("panes") or {}).get("rep") or {}


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1106-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tag = "after_" if after else "before_"
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required",
                                                                "--mute-audio"])
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
            for _ in range(90):
                if (state().get("audio") or {}).get("jukebox"):
                    break
                time.sleep(1)
            print("jukebox button:", (state().get("audio") or {}).get("jukebox"), flush=True)
            time.sleep(2)
            rel = "audio/idx0200 - Drive My Car.wav"
            page.locator(".aud-name", has_text="Drive My Car").first.click()
            time.sleep(1.5)
            rep_pane = page.locator(".aud-pane").nth(1)
            rep_pane.locator("button:has-text('Play')").first.click()
            time.sleep(2.5)
            got = _rep(state)
            print("rep pane:", got.get("base"), "|", got.get("name"), "|", got.get("hint"), flush=True)
            page.mouse.move(5, 890)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, tag + "audio_jukebox_row.png"))
            if after:
                names = [got.get("name")]
                for _ in range(5):
                    rep_pane.locator("button[aria-label='Stop']").first.click()
                    time.sleep(0.5)
                    rep_pane.locator("button:has-text('Play')").first.click()
                    time.sleep(1.5)
                    names.append(_rep(state).get("name"))
                print("draws after stop + play:", names, flush=True)
            print("selected:", (state().get("audio") or {}).get("sel"), "want", rel, flush=True)
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
