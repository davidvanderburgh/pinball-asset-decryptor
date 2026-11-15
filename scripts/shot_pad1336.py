"""PAD-1336 proof shot: what the Multi-boot tab says when a card's verify fails.

    python scripts/shot_pad1336.py <out-dir> <name> <verify log> <card path>

writes <out-dir>/<name>.png: the app on a Stern project, Multi-boot tab, with the status
line a failed verify leaves - computed by THIS tree's own code from a real verify log (the
same expression Build & verify's done callback uses), so main's export shows main's line
and the branch shows the branch's.  The server runs against a scratch settings folder (the
shot_pad980.py rig).
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import sys, threading
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import multiboot_panel as mp
from pinball_decryptor.webui import multiboot_core as mc
from pinball_decryptor.webui import host
LOG = open(%(log)r, encoding="utf-8", errors="replace").read()
why = (getattr(mc, "failure_why", None) or mc.parse_refusal)(LOG, %(card)r)
MSG = "%%s failed (exit %%d) - %%s" %% ("verify", 1, why or "see the tool output.")
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    r = _orig(self, *a, **k)
    if not getattr(self, "_pad1336_done", False):
        self._pad1336_done = True
        threading.Timer(2.0, lambda: self._error(MSG)).start()
    return r
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def shoot(out_dir, name, log, card, wait):
    scratch = tempfile.mkdtemp(prefix="pad1336-")
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "log": log, "card": card})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python")})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        time.sleep(4)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(wait)
            out = os.path.join(out_dir, "%s.png" % name)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    out_dir, name, log, card = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    os.makedirs(out_dir, exist_ok=True)
    shoot(out_dir, name, os.path.abspath(log), card, float(os.environ.get("PAD1336_WAIT", "3")))


if __name__ == "__main__":
    main()
