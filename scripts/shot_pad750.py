"""PAD-750 proof shots: the Defaults tab's "Default setting" editor for
Balls Per Game, and the settings form's row for it.

    python scripts/shot_pad750.py <repo> <card.raw> <out_dir> <prefix> [after]

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of main for the "before" shots).  Writes <out_dir>/<prefix>_editor.png (the
editor open on Balls Per Game) and <prefix>_form.png (the settings form).
With ``after`` the editor's Highest field is set to 15 and the default to 12
before the editor shot, and OK pressed before the form shot.  The card is
only read; staging goes to a scratch project folder.
"""

import json
import re
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

ROW = r"BALLS PER GAME\s+\(0x"


def main():
    repo = os.path.abspath(sys.argv[1])
    card = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])
    prefix = sys.argv[4]
    after = len(sys.argv) > 5 and sys.argv[5] == "after"
    scratch = tempfile.mkdtemp(prefix="pad750-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch750.py")
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
            time.sleep(1)
            # the list draws only the rows in view: A-Z brings B to the top
            webui_shot.api(url, "defaults.sort_all", "setting")
            time.sleep(1)
            page.locator(".dflt-all").scroll_into_view_if_needed()
            row = page.locator(".dflt-all").get_by_text(re.compile("^" + ROW)).first
            for _ in range(60):
                if row.count():
                    break
                page.locator(".dflt-all .scroller").first.evaluate("e => e.scrollTop += 150")
                time.sleep(0.2)
            row.scroll_into_view_if_needed()
            row.dblclick()
            page.wait_for_selector(".dflt-edit", timeout=10000)
            time.sleep(0.5)
            if after:
                page.locator("#dflt-hi").fill("15")
                page.locator("#dflt-new").fill("12")
                time.sleep(0.5)
            out = os.path.join(out_dir, "%s_editor.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            if after:
                page.get_by_role("button", name="OK").click()
            else:
                page.get_by_role("button", name="Cancel").click()
            time.sleep(1.5)
            page.get_by_text("Balls Per Game", exact=True).first.scroll_into_view_if_needed()
            time.sleep(0.5)
            out = os.path.join(out_dir, "%s_form.png" % prefix)
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
