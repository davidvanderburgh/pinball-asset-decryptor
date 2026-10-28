"""PAD-786 proof shot: the Defaults tab on a card whose final wizard ends the game
(Godzilla LE 1.16), where the Final wizard box sits above the settings.

    python scripts/shot_pad786.py <repo> <card.raw> <out_png> [after]

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of main for the "before" shot).  With ``after`` the "The final wizard does not end
the game" box is ticked before the shot.  The card is only read; staging
goes to a scratch project folder.
"""

import json
import os
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


def main():
    repo = os.path.abspath(sys.argv[1])
    card = os.path.abspath(sys.argv[2])
    out = os.path.abspath(sys.argv[3])
    after = len(sys.argv) > 4 and sys.argv[4] == "after"
    scratch = tempfile.mkdtemp(prefix="pad786-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch786.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "defaults")
            page.wait_for_selector(".dflt-all", timeout=120000)
            time.sleep(1.5)
            if after:
                page.get_by_text("The final wizard does not end the game").click()
                time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            staged = os.path.join(project, ".staged_changes.json")
            if os.path.isfile(staged):
                print("staged:", open(staged, encoding="utf-8").read(), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
