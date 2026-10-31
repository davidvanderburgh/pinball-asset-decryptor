"""PAD-903 proof shot: the Multi-boot tab on a Mac whose Colima does not
share the folder the ISOs are in (/Volumes/<disk>).

    python scripts/shot_pad903.py <repo> <out_png>

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of main for the "before" shot).  Nothing runs Docker or Colima: the
launcher stands the Mac in (``multiboot_docker.enabled``), has the
container check answer "cannot see /Volumes/Mac SSD/isos" the way colima
does, and starts a writing run as the tab is shown.  Before: the Log's
sentence with the Terminal lines.  After: the offer to restart Colima.
"""

import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import os
import sys
# the tab's own run guard, not the rig: nothing below reaches a tool (the
# container check stops the run, and nobody answers the offer)
os.environ["PAD_UI_NO_RIG"] = "0"
sys.path.insert(0, %r)
from pinball_decryptor.webui import multiboot_docker as D
from pinball_decryptor.webui import multiboot_core as mt
UNSEEN = ["/Volumes/Mac SSD/isos"]
D.enabled = lambda: True
D._engine_name = lambda: "colima"
D.colima_fix = lambda unseen: [["colima", "stop"],
                               ["colima", "start", "--mount", "/Users/me:w",
                                "--mount", "/Volumes:w"]]


def ensure(paths, repo, log=None, D=D, UNSEEN=UNSEEN):
    if hasattr(D, "Unshared"):
        raise D.Unshared(UNSEEN)
    raise RuntimeError(D.unshared_reason(UNSEEN))


D.ensure_container = ensure
_shown = mt.MultibootPanel.on_shown


def on_shown(self, *a, _shown=_shown, **k):
    try:
        r = _shown(self, *a, **k)
        self._run_commands([("build", ["true"])])
    except Exception:
        import traceback
        with open(%r + ".err", "w") as fh:
            traceback.print_exc(file=fh)
        raise
    return r


mt.MultibootPanel.on_shown = on_shown
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad903-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch903.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, out))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {
                       "extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            # the dialog holds the call open until it is answered
            threading.Thread(target=lambda: webui_shot.api(
                url, "ui.select_tab", "multiboot"), daemon=True).start()
            time.sleep(6)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
