"""PAD-327 proof shot: Install Missing on Windows when the elevated
PowerShell window never starts the installer (blank window on hotel Wi-Fi).

    python scripts/shot_pad327.py <out.png>

The server runs from THIS tree against a scratch settings folder:

- every WSL probe fails as "WSL is not installed" (the Spike 2 strip the
  user had);
- the elevated PowerShell is a stand-in that stays open and never writes
  the started marker, and the 45 s grace is cut to 3 s;
- a tree from before PAD-327 has no prereq_launch, so there the old
  ``Start-Process`` Popen is swallowed instead.

It presses Install Missing, waits 10 s and photographs the page.
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
import subprocess, sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import prereqs
prereqs._probe_wsl = lambda cmd: (
    False, "WSL is not installed on this machine.",
    "Click 'Install Missing' above the tabs - it installs WSL2 + Ubuntu "
    "and asks for one Windows restart.")
_popen = subprocess.Popen
def _popen_no_ps(argv, *a, **kw):
    if isinstance(argv, list) and argv and argv[0] == "powershell" \
            and "Start-Process" in " ".join(argv):
        print("swallowed old launch:", argv, flush=True)
        return None
    return _popen(argv, *a, **kw)
subprocess.Popen = _popen_no_ps
try:
    from pinball_decryptor.core import prereq_launch
except ImportError:
    prereq_launch = None
if prereq_launch is not None:
    class _BlankWindow:
        error = 0
        declined = False
        def __init__(self, args, cwd=None):
            print("elevated console:", args, cwd, flush=True)
        def running(self):
            return True
        def close(self):
            pass
    prereq_launch.ElevatedConsole = _BlankWindow
    _watch = prereq_launch.watch_started
    prereq_launch.watch_started = lambda m, r: _watch(m, r, grace_s=3)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    out = os.path.abspath(sys.argv[1])
    scratch = tempfile.mkdtemp(prefix="pad327-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project}}},
                  f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_PREREQS": ""}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "extract")
        time.sleep(8)
        webui_shot.api(url, "shellx.install_prereqs")
        time.sleep(10)
        st = webui_shot.state(url)
        print("modals:", json.dumps(st.get("modals"))[:600], flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
