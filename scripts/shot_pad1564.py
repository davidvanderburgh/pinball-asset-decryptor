"""PAD-1564 proof shots: WSL installed, Windows' Virtual Machine Platform off.

    python scripts/shot_pad1564.py <out_dir> <before|after>

The server runs from THIS tree against a scratch settings folder, with only
the machine facts of the reporter's PC faked underneath the diagnosis code
(which runs for real):

- ``wsl -l -q`` lists Ubuntu-24.04 (WSL 2) and ``wsl --status`` exits 0;
- every command inside it fails with his French "a required feature is not
  installed" error, which carries no error code;
- the Hyper-V compute service (vmcompute) does not exist;
- the app's own Linux is absent, and the elevated installer is a stand-in.

Writes <prefix>_prereqs.png (the JJP Extract page after the check) and
<prefix>_install_missing.png (the question Install Missing asks).
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
from pinball_decryptor.core import prereqs, runtime
ERR = ("L'opération n'a pas pu être démarrée car une fonctionnalité requise "
       "n'est pas installée. ")
prereqs._wsl_distro_registered = lambda: True
prereqs._wsl_status_ok = lambda: True
prereqs._wsl_default_distro = lambda want=None: ("Ubuntu-24.04", 2)
prereqs.wsl_release = lambda *a, **k: ("", "", "")
prereqs._virtualization_disabled = lambda: False
prereqs._wsl_restart_pending = lambda: False
prereqs._vm_platform_off = lambda: True     # absent before PAD-1564: unused
prereqs._run_in_wsl = lambda cmd, timeout: subprocess.CompletedProcess(
    ["wsl"], 1, stdout="", stderr=ERR)
runtime.status = lambda *a, **k: ("absent", "not installed")
runtime.wsl_distro = lambda *a, **k: None
from pinball_decryptor.core import prereq_launch
class _Console:
    error = 0
    declined = False
    def __init__(self, args, cwd=None):
        print("elevated console:", args, flush=True)
    def running(self):
        return False
    def close(self):
        pass
prereq_launch.ElevatedConsole = _Console
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def _shot(url, out, hover=None):
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url)
        page.wait_for_function("window.__padReady === true", timeout=60000)
        time.sleep(3)
        if hover:
            # the red chip's tooltip carries the whole diagnosis
            page.locator(hover).first.hover()
            time.sleep(1.5)
        page.screenshot(path=out)
        browser.close()
    print("shot", out, os.path.getsize(out), flush=True)


def main():
    out_dir, prefix = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1564-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_output": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_PREREQS": ""}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        webui_shot.api(url, "ui.select_tab", "extract")
        time.sleep(10)
        _shot(url, os.path.join(out_dir, prefix + "_prereqs.png"),
              hover=".sx-prereq-chips .chip")
        webui_shot.api(url, "shellx.install_prereqs")
        time.sleep(6)
        st = webui_shot.state(url)
        print("modals:", json.dumps(st.get("modals"))[:900], flush=True)
        _shot(url, os.path.join(out_dir, prefix + "_install_missing.png"))
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
