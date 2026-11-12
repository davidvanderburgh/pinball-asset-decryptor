r"""PAD-1190 proof shot: a JJP song clip's Video tab row names its song and plays it along.

    python scripts/shot_pad1190.py <app tree> <out png> [--play]

Serves <app tree> (main for "before", the ticket branch for "after") on a scratch Guns N' Roses project
built in C:\tmp\PAD-1190\proj from

- the Civil War clips of GnR 3.03 (PAD1190_VIDEOS, default D:\Pinball\videos\Guns N Roses), placed
  where the card keeps them (graphics/Songs/CivilWar, graphics/Songs/Intro), and
- the sounds a sounds-only extract of GnR 3.03 wrote (PAD1190_SOUNDS, default C:\tmp\PAD-1190\gnr\sound):
  the Civil War song, its fanfares and the song-target sounds,

then opens the Video tab on live_edited_CivilWar.webm. With --play it presses Play on the Original
player, lets it run, seeks it, and prints where the song is against the clip (every Audio the page makes
is recorded by an init script), so the shot shows the clip mid-play with its song following.
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
import webui_shot  # noqa: E402

VIDEOS = os.environ.get("PAD1190_VIDEOS", r"D:\Pinball\videos\Guns N Roses")
SOUNDS = os.environ.get("PAD1190_SOUNDS", r"C:\tmp\PAD-1190\gnr\sound")
PROJECT = r"C:\tmp\PAD-1190\proj"
CLIPS = {"graphics/Songs/CivilWar": ("live_edited_CivilWar.webm", "stage_video_CivilWar.webm"),
         "graphics/Songs/Intro": ("Song_Intro_CivilWar.a.webm",)}
SOUND_DIRS = ("music/CivilWar", "music/TearDownTheWall", "fanfare/civil_war", "fx/lit_song_target")
ROW = "live_edited_CivilWar"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

#: every Audio the page makes, for the --play report
AUDIO_SPY = """
(() => { const A = window.Audio; window.__audios = [];
  window.Audio = function (src) { const a = new A(src); window.__audios.push(a); return a; };
  window.Audio.prototype = A.prototype; })();
try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}
"""


def _project():
    if os.path.isdir(PROJECT):
        return PROJECT
    for folder, names in CLIPS.items():
        os.makedirs(os.path.join(PROJECT, *folder.split("/")))
        for n in names:
            shutil.copy2(os.path.join(VIDEOS, n), os.path.join(PROJECT, *folder.split("/"), n))
    for d in SOUND_DIRS:
        shutil.copytree(os.path.join(SOUNDS, *d.split("/")), os.path.join(PROJECT, "sound", *d.split("/")))
    # what an extract leaves: every file's checksum, so the files read as the card's own
    lines = []
    for root, _dirs, files in os.walk(PROJECT):
        for n in sorted(files):
            path = os.path.join(root, n)
            with open(path, "rb") as f:
                lines.append("%s\t%s\n" % (os.path.relpath(path, PROJECT).replace(os.sep, "/"),
                                            hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(PROJECT, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(sorted(lines))
    return PROJECT


def _report(page):
    return page.evaluate("""() => {
      const v = [...document.querySelectorAll('.vid-pane video')].find((x) => !x.paused) || null;
      const a = (window.__audios || []).filter((x) => /BEAT_MAP/.test(x.src));
      return {video: v ? +v.currentTime.toFixed(2) : null,
              songs: a.map((x) => ({t: +x.currentTime.toFixed(2), paused: x.paused,
                                    src: decodeURIComponent(x.src).split('/').pop()}))}; }""")


def main():
    tree, out_png = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    play = "--play" in sys.argv
    project = _project()
    scratch = tempfile.mkdtemp(prefix="pad1190-")
    launcher = os.path.join(scratch, "launch1190.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % tree)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_output": project, "write_assets": project,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required",
                                                                "--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(AUDIO_SPY)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(10)
            page.get_by_placeholder("Search").first.fill("civil")
            time.sleep(2)
            page.locator(".vid-name", has_text=ROW).first.click()
            time.sleep(6)
            sounds = page.locator(".vid-sounds")
            print("callout:", sounds.inner_text().replace("\n", " | ") if sounds.count() else None, flush=True)
            if play:
                page.locator(".vid-pane").first.locator("button:has-text('Play')").click()
                time.sleep(4)
                print("playing:", _report(page), flush=True)
                page.evaluate("""() => { const v = [...document.querySelectorAll('.vid-pane video')]
                  .find((x) => !x.paused); if (v) v.currentTime = 200; }""")
                time.sleep(3)
                print("after seek to 200 s:", _report(page), flush=True)
                page.locator(".vid-pane").first.locator("button:has-text('Pause')").click()
                time.sleep(1)
                print("paused:", _report(page), flush=True)
            page.mouse.move(5, 895)
            time.sleep(1)
            page.screenshot(path=out_png)
            print("shot", out_png, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
