"""PAD-435 proof shots: a James Bond card picked on the Select card tab while a Godzilla
project is open.

    python scripts/shot_pad435.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  A scratch project "Godzilla LE 1.16" holds an extract of the stock
Godzilla LE 1.16 card (its ``.extract_source.json``, ``.checksums.md5`` and anchor); the
app opens on it with that card picked.  Then the James Bond 007 LE 1.06 card is picked on
the Select card tab, as Browse... or the recent list does, and two shots are taken:

* ``<prefix>_select_card.png``: the tab a few seconds after the pick;
* ``<prefix>_select_card_stay.png``: the same tab once the offer (if any) is closed with
  the button that keeps the Godzilla project open;
* ``<prefix>_extract.png``: the Extract tab after that.

Both cards are stand-in files of a few bytes that the server recognises by name (the
Spike 2 partition probe is replaced in the served process only).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

HOST = r'''
import os, sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import manufacturer as M
_real = M.detect_game
def _by_name(path, *a, **k):
    name = os.path.basename(path).lower()
    if os.path.dirname(os.path.abspath(path)).lower() == %(scratch)r.lower():
        for key in ("godzilla", "james_bond"):
            if name.startswith(key):
                return key
    return _real(path, *a, **k)
M.detect_game = _by_name
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

STOCK = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
BOND = "james_bond_le-1_06_0.Release.16G.sdcard.raw"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = os.path.normpath(tempfile.mkdtemp(prefix="pad435-"))
    project = os.path.join(scratch, "Godzilla LE 1.16")
    os.makedirs(os.path.join(project, "audio"))
    stock = os.path.join(scratch, STOCK)
    bond = os.path.join(scratch, BOND)
    for p, n in ((stock, 64), (bond, 96)):
        with open(p, "wb") as f:
            f.write(b"\0" * n)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": stock, "input_name": STOCK, "size": 64}, f)
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("d41d8cd98f00b204e9800998ecf8427e  audio/x.wav\n")
    sys.path.insert(0, repo)
    from pinball_decryptor.core import project_file
    project_file.save(project_file.anchor_path(project), manufacturer_key="stern",
                      paths={"extract_input": stock, "extract_output": project,
                             "write_assets": project},
                      extract_options={}, stock_image=stock)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "scratch": scratch})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "project_dir": scratch,
                   "manufacturers": {"stern": {"extract_input": stock,
                                               "extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", repo, "scratch", scratch, flush=True)
    try:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "card")
            time.sleep(4)
            webui_shot.api(url, "extract.use_recent", "input", bond)
            time.sleep(6)
            shot = os.path.join(out_dir, "%s_select_card.png" % prefix)
            page.screenshot(path=shot)
            print("shot", shot, flush=True)
            stay = page.get_by_role("button", name="Stay in Godzilla LE 1.16")
            if stay.count():
                stay.first.click()
                time.sleep(2)
            shot = os.path.join(out_dir, "%s_select_card_stay.png" % prefix)
            page.screenshot(path=shot)
            print("shot", shot, flush=True)
            webui_shot.api(url, "ui.select_tab", "extract")
            time.sleep(3)
            shot = os.path.join(out_dir, "%s_extract.png" % prefix)
            page.screenshot(path=shot)
            print("shot", shot, flush=True)
            st = webui_shot.state(url)
            print("project", st["extract"]["project"]["folder"], flush=True)
            print("card", st["extract"]["input"], flush=True)
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
