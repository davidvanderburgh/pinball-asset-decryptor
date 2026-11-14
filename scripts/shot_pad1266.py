r"""PAD-1266 proof shot: the Video tab's song note for a JJP song clip, before and after it was
made one line.

    python scripts/shot_pad1266.py <app tree> <out png>

Serves <app tree> (main for "before", the ticket branch for "after") on a scratch Guns N' Roses
project built in C:\tmp\PAD-1266\proj from the Civil War clips of GnR 3.03 (PAD1266_VIDEOS, default
D:\Pinball\videos\Guns N Roses) and a quiet stand-in for the song the game plays with
live_edited_CivilWar.webm (sound/music/CivilWar/BG_GnR_BEAT_MAP_CivilWar.ogg, made by ffmpeg at the
clip's own length: the note matches songs by name and length only). Opens the Video tab on that clip
and prints the note's text and height.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

VIDEOS = os.environ.get("PAD1266_VIDEOS", r"D:\Pinball\videos\Guns N Roses")
PROJECT = r"C:\tmp\PAD-1266\proj"
CLIPS = {"graphics/Songs/CivilWar": ("live_edited_CivilWar.webm", "stage_video_CivilWar.webm")}
SONG = "sound/music/CivilWar/BG_GnR_BEAT_MAP_CivilWar.ogg"
ROW = "live_edited_CivilWar"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _project():
    if os.path.isfile(os.path.join(PROJECT, *SONG.split("/"))):
        return PROJECT
    for folder, names in CLIPS.items():
        os.makedirs(os.path.join(PROJECT, *folder.split("/")), exist_ok=True)
        for n in names:
            shutil.copy2(os.path.join(VIDEOS, n), os.path.join(PROJECT, *folder.split("/"), n))
    clip = os.path.join(PROJECT, "graphics", "Songs", "CivilWar", ROW + ".webm")
    secs = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", clip], text=True).strip())
    song = os.path.join(PROJECT, *SONG.split("/"))
    os.makedirs(os.path.dirname(song), exist_ok=True)
    subprocess.check_call(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                           "anullsrc=r=44100:cl=stereo", "-t", "%.2f" % secs, "-c:a", "libvorbis", song])
    return PROJECT


def main():
    tree, out_png = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    print("tree:", tree, flush=True)
    project = _project()
    scratch = tempfile.mkdtemp(prefix="pad1266-")
    launcher = os.path.join(scratch, "launch1266.py")
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
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(10)
            page.get_by_placeholder("Search").first.fill("civil")
            time.sleep(2)
            page.locator(".vid-name", has_text=ROW).first.click()
            time.sleep(8)
            sounds = page.locator(".vid-sounds")
            if sounds.count():
                box = sounds.bounding_box()
                print("note:", sounds.inner_text().replace("\n", " | "), flush=True)
                print("note height: %.0f px" % box["height"], flush=True)
                tipped = page.locator(".vid-sounds [data-tip]").evaluate_all(
                    "(els) => els.map((e) => e.getAttribute('data-tip'))")
                print("tips:", tipped, flush=True)
            else:
                print("note: none", flush=True)
            page.mouse.move(5, 895)
            time.sleep(1)
            page.screenshot(path=out_png)
            print("shot", out_png, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
