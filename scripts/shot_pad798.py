"""PAD-798 proof shots: the Write tab's Game points (every point the game adds, times N).

    python scripts/shot_pad798.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder whose Stern project
is taken for a TMNT LE 1.59 card. "after" sets the project's Game points to x10 through the tab's own
call before the shot, so the note under the choice shows. Shot: <before|after>_write_tab.png, the Write
tab's build options (the code before PAD-798 has no Game points row).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import mode_project as MP
PROF = MP.profile(next(k for k in MP.profiles() if k.startswith("turtles_le")))
try:
    from pinball_decryptor.plugins.stern import game_points as GP
    GP.project_title = lambda project, probe=False: PROF
except ImportError:                     # the code before PAD-798
    pass
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad798-")
    project = os.path.join(scratch, "TMNT project")
    os.makedirs(project)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", repo, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "write")
        if which == "after":
            print("set_points", webui_shot.api(url, "write.set_points", 10), flush=True)
        time.sleep(3)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            row = page.get_by_text("Game points", exact=True)
            print("game points rows", row.count(), flush=True)
            if row.count():
                row.first.scroll_into_view_if_needed()
            else:
                ed = page.get_by_text("Editions", exact=True)
                if ed.count():
                    ed.first.scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "%s_write_tab.png" % which))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
