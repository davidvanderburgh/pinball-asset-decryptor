"""PAD-659 proof shot: the Emulate tab on a PC whose own WSL logs in as root
and has no PAD-Runtime yet (what the app's own installer leaves behind).

    python scripts/shot_pad659_root.py <repo> <out.png>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of
main for the "before" shot).  Nothing runs on the rig (``PAD_UI_NO_RIG``): the
setup facts the reporter's log showed (every package present, ``user: root``)
and the runtime state ``absent`` are handed to the tab as its setup check and
status poll would.
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
from pinball_decryptor.webui.tabs import emulate as E
from pinball_decryptor.webui import runtime_prompt

runtime_prompt.can_install = lambda: True
FACTS = {"iswsl": "1", "binfmt": "1", "user": "root", "interop": "1",
         "display": "ok", "distro": "ubuntu 24.04 noble", "winaudio": "1",
         "winpf": "1", "wslconf": "1"}
_build = E.EmulateTab._build


def build(self):
    _build(self)
    self._setup_apply(dict(FACTS))
    self._runtime_apply(("absent", "not installed"))


E.EmulateTab._build = build
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad659r-")
    print("repo", repo, flush=True)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"},
                  f)
    launcher = os.path.join(scratch, "launch659r.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "PAD_SLOT": ""}
    proc, url = webui_shot.start_server(settings, scratch,
                                        app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1');"
                " localStorage.setItem('pad.log.h', '160'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(4)
            page.mouse.move(5, 995)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
