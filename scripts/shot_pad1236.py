"""PAD-1236 proof shots: Project > Team... (several PCs working on one project).

    python scripts/shot_pad1236.py <repo> <out_dir> <before|after>

Serves <repo> on a scratch project (this PC: "Dave", who owns Scenes) beside a
scratch team folder where a teammate ("Alex", the Videos) has already shared,
then shoots:

* ``<tag>_project_menu.png``: the Project menu open (after: it has "Team...")
  and the top bar (after: the "Team: 1 new" chip, Alex's Videos waiting).
* ``<tag>_team_window.png``: after, the Team window that entry opens; before,
  the same menu (there was no such window).
* ``after_team_got.png`` (after only): the window once Get from the team has
  run, the project's own record printed to the console.

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


def make_project(scratch, name, staged):
    project = os.path.join(scratch, name)
    os.makedirs(project)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(staged, f, indent=1)
    card = "godzilla_pro-1_20_0.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    for rel in ("videos/attract/GZ_Intro.mp4", "videos/modes/Kaiju_Award.mp4",
                "audio/callouts/gz_jackpot.wav", "images/score/bg_1.png"):
        _file(os.path.join(project, *rel.split("/")), 1000)
    import hashlib
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        for rel in ("videos/attract/GZ_Intro.mp4", "videos/modes/Kaiju_Award.mp4",
                    "audio/callouts/gz_jackpot.wav", "images/score/bg_1.png"):
            with open(os.path.join(project, *rel.split("/")), "rb") as g:
                f.write("%s\t%s\n" % (rel, hashlib.md5(g.read()).hexdigest()))
    tex = os.path.join(project, "images", "scene_textures")
    os.makedirs(tex, exist_ok=True)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    tag = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1236-")
    lib = os.path.join(scratch, "Alex clips")
    team = os.path.join(scratch, "OneDrive", "GZ team")
    # Alex's PC: the Videos
    alex = make_project(scratch, "alex_godzilla", {
        "video": {"videos/attract/GZ_Intro.mp4": _file(os.path.join(lib, "my intro.mp4"), 300000),
                  "videos/modes/Kaiju_Award.mp4": _file(os.path.join(lib, "kaiju award.mp4"), 300000)}})
    # this PC (Dave): the Scenes
    project = make_project(scratch, "godzilla_pro-1_20", {"settings": {"AD_BALLS_PER_GAME": 5}})
    with open(os.path.join(project, "images", "scene_textures", "scene_edits.json"), "w",
              encoding="utf-8") as f:
        json.dump({"/gz/attract/scene.radium": [{"op": "move", "node": 5, "dx": 3, "dy": 4}]}, f)
    if tag == "after":
        sys.path.insert(0, repo)
        from pinball_decryptor.core import team_sync as TS
        TS.join(alex, team, "Alex")
        TS.claim(alex, ["videos"])
        TS.share(alex, game="Godzilla Pro 1.20")
        TS.join(project, team, "Dave")
        TS.claim(project, ["scenes"])
    launcher = os.path.join(scratch, "launch1236.py")
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
            time.sleep(6 if tag == "after" else 3)       # the team folder's first look
            page.locator("[aria-label='Project menu']").first.click()
            time.sleep(1.2)
            menu = os.path.join(out_dir, "%s_project_menu.png" % tag)
            page.screenshot(path=menu)
            print("shot", menu, flush=True)
            win = os.path.join(out_dir, "%s_team_window.png" % tag)
            if tag == "before":
                shutil.copy2(menu, win)
                print("shot", win, "(no such window: the menu again)", flush=True)
            else:
                page.get_by_text("Team", exact=False).filter(has_text="…").first.click()
                time.sleep(2.5)
                page.screenshot(path=win)
                print("shot", win, flush=True)
                page.locator(".sx-team .ft").get_by_text("Get", exact=False).first.click()
                time.sleep(5)
                done = os.path.join(out_dir, "after_team_got.png")
                page.screenshot(path=done)
                print("shot", done, flush=True)
                with open(os.path.join(project, ".staged_changes.json"), encoding="utf-8") as f:
                    print(json.dumps(json.load(f), indent=1), flush=True)
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
