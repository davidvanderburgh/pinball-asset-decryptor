r"""PAD-953 proof shot: the Emulate Spooky tab as a Mac sees it.

    python scripts/shot_pad953.py <app tree> <out.png>

<app tree> is a checkout or a `git archive` export (main for "before", the
ticket branch for "after").  The Spooky tab's core module is told it runs on
macOS (its own ``sys`` only; the rest of the app stays on Windows), with
Alice Cooper's update file picked.  Nothing runs in WSL or Docker
(PAD_UI_NO_RIG).
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
import sys, types
sys.path.insert(0, %(tree)r)
from pinball_decryptor.webui import emulate_spooky_core as core
class _Mac(types.ModuleType):
    platform = "darwin"
    def __getattr__(self, name):
        return getattr(sys, name)
core.sys = _Mac("sys")
core.rig_available = lambda: True
from pinball_decryptor.webui.tabs import emulate_spooky
T = emulate_spooky.EmulateSpookyTab
_init = T.__init__
def __init__(self, window):
    _init(self, window)
    self.spooky_emulate_file_var.set("/Users/me/Downloads/ac-gamecode.pkg")
T.__init__ = __init__
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    tree, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad953-")
    launcher = os.path.join(scratch, "launch953.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "spooky"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_TICKET": "", "PAD_SLOT": ""}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env,
                                        app_cmd=[sys.executable, launcher])
    print("tree", tree, "server", url.split("?")[0])
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "spooky")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate_spooky")
            time.sleep(4)
            st = webui_shot.state(url).get("emulate_spooky", {})
            print("rig_ok:", st.get("rig_ok"), "| go_enabled:", st.get("go_enabled"),
                  "| note:", st.get("note"))
            page.screenshot(path=out)
            print("shot", out)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
