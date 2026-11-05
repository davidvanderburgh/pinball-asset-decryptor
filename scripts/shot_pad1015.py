"""PAD-1015 proof shots: Project > Export replacement files.

    python scripts/shot_pad1015.py <repo> <out_dir> <before|after>

Serves <repo> on a scratch project whose sidecar records replacements from a
scratch "library" (videos, random clips, sounds, a music mode file, pictures),
then shoots:

* ``<tag>_project_menu.png``: the Project menu open (after: it has "Export
  replacement files...").
* ``<tag>_export_window.png``: after, the window that entry opens, its folder
  filled in; before, the same menu (there was no such window).
* ``after_export_done.png`` (after only): the window once Export has run, and
  the export folder's listing printed to the console.

Needs Playwright (the user site-packages one) and the installed Edge.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _file(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(size))
    return path


def make_project(scratch):
    lib = os.path.join(scratch, "GZ mods")
    project = os.path.join(scratch, "godzilla_pro-1_20")
    os.makedirs(project)
    v = lambda n: _file(os.path.join(lib, "clips", n), 300000)       # noqa: E731
    a = lambda n: _file(os.path.join(lib, "callouts", n), 90000)     # noqa: E731
    i = lambda n: _file(os.path.join(lib, "art", "scores", n), 20000)  # noqa: E731
    staged = {
        "video": {"videos/attract/GZ_Intro.mp4": v("my intro.mp4"),
                  "videos/modes/Kaiju_Award.mp4": v("kaiju award.mp4"),
                  "videos/modes/Gigan_Award.mp4": v("kaiju award.mp4")},
        "video_variants": {"videos/attract/GZ_Intro.mp4": [
            v("intro take 2.mp4"), _file(os.path.join(lib, "old", "my intro.mp4"), 310000)]},
        "audio": {"audio/callouts/gz_jackpot.wav": a("jackpot.wav"),
                  "audio/callouts/gz_super.wav": a("super jackpot.wav")},
        "sound_modes": {"names": ["", "Doom"], "slots": {
            "audio/music/gz_main.wav": {"2": _file(os.path.join(lib, "music", "doom theme.wav"), 400000)}}},
        "image": {"images/score/bg_1.png": i("bg red.png"),
                  "images/score/bg_2.png": i("bg blue.png")},
    }
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(staged, f, indent=1)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    tag = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1015-")
    project = make_project(scratch)
    export = os.path.join(scratch, "GZ export")
    launcher = os.path.join(scratch, "launch1015.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            page.locator("[aria-label='Project menu']").first.click()
            time.sleep(1.2)
            menu = os.path.join(out_dir, "%s_project_menu.png" % tag)
            page.screenshot(path=menu)
            print("shot", menu, flush=True)
            win = os.path.join(out_dir, "%s_export_window.png" % tag)
            if tag == "before":
                shutil.copy2(menu, win)
                print("shot", win, "(no such window: the menu again)", flush=True)
            else:
                page.get_by_text("Export replacement files", exact=False).first.click()
                time.sleep(2)
                field = page.locator(".sx-export input").first
                field.fill(export)
                field.press("Tab")
                time.sleep(1.5)
                page.screenshot(path=win)
                print("shot", win, flush=True)
                page.locator(".sx-export .ft").get_by_text("Export", exact=False).first.click()
                time.sleep(4)
                # the message box saying what was done
                done = os.path.join(out_dir, "after_export_done.png")
                page.screenshot(path=done)
                print("shot", done, flush=True)
                for root, _dirs, files in os.walk(export):
                    for n in sorted(files):
                        print("  exported:", os.path.relpath(os.path.join(root, n), export), flush=True)
                with open(os.path.join(project, ".staged_changes.json"), encoding="utf-8") as f:
                    print(json.dumps(json.load(f), indent=1), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
