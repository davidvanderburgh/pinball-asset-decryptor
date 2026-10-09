"""PAD-490 proof shot: the Stern prerequisite check on a PC whose WSL is
stuck (after a hang every wsl.exe call timed out), so the strip and the log
said "WSL is not installed on this machine" while Task Manager showed it
running.

    python scripts/shot_pad490.py <out.png>

The server runs from THIS tree against a scratch settings folder:

- every wsl.exe call raises TimeoutExpired at once (the user's 8 s and 20 s
  waits, without the waiting);
- the registry lists one distro, Ubuntu, whatever this PC has.  A tree from
  before PAD-490 never reads it.

It opens Stern's Extract tab, waits for the check to finish and photographs
the page with the log showing the WSL2 row's problem and fix.
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
import os, subprocess, sys
sys.path.insert(0, %(repo)r)
_run = subprocess.run
def _stuck(argv, *a, **kw):
    head = argv[0] if isinstance(argv, (list, tuple)) else str(argv).split()[0]
    if os.path.basename(str(head)).lower() in ("wsl", "wsl.exe"):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout") or 0)
    return _run(argv, *a, **kw)
subprocess.run = _stuck
from pinball_decryptor.core import wsl_disk
wsl_disk.registered_distro_names = lambda: ["Ubuntu"]
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    out = os.path.abspath(sys.argv[1])
    scratch = tempfile.mkdtemp(prefix="pad490-")
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
        deadline = time.time() + 120
        rows = []
        while time.time() < deadline:
            rows = (webui_shot.state(url).get("shell") or {}).get("prereqs") or []
            if rows and all(r["state"] != "checking" for r in rows):
                break
            time.sleep(1)
        for r in rows:
            print("prereq", r["name"], r["state"], "|", r["message"], "|",
                  r["hint"], flush=True)
        time.sleep(3)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1');"
                " localStorage.setItem('pad.log.h', '330'); } catch (e) {}")
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
