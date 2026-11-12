r"""PAD-1197 proof shot: the Emulate tab's "Leave out of this run" ticks.

    python scripts/shot_pad1197.py <app tree> <out.png> <card.raw> <project> [kind,kind...]

<app tree> is a checkout or a `git archive` export (main for "before", the
ticket branch for "after").  The tab has <card.raw> picked, "Apply my replaced
assets" ticked and <project> as the Write tab's assets folder (a Godzilla Pro
1.16 extract with a music mode, random clips and a mode).  The kinds named last
are ticked through the page's own call before the shot.  The rig's probes are
stubbed, so nothing runs in WSL; the app runs on a scratch settings file.
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
import subprocess, sys
sys.path.insert(0, %(tree)r)
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
emulate_rig.status_cmd = lambda: ["status.sh"]
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda: 0
from pinball_decryptor.webui.tabs import emulate
T = emulate.EmulateTab
emulate._slots_here = lambda: True
for name in ("_precache_kick", "_select_probe_kick", "_backup_kick", "_setup_check",
             "_reattach_data_disk", "_note_the_runtime_is_a_different_machine", "_editions_kick",
             "_which_kick", "_mains_kick", "_spike3_kick", "slots_refresh"):
    if hasattr(T, name):
        setattr(T, name, lambda self, *a, **k: None)
class _Done:
    def __init__(self, out):
        self.stdout, self.stderr, self.returncode = out, b"", 0
def _run(self, cmd, **kw):
    if cmd == ["status.sh"]:
        return _Done(b"state=off\nprocs=0\n")
    return _Done(b"")
T._run = _run
T._popen = lambda self, cmd, **kw: subprocess.Popen([sys.executable, "-c", "pass"])
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    tree, out, card, proj = (os.path.abspath(a) for a in sys.argv[1:5])
    kinds = [k for k in (sys.argv[5] if len(sys.argv) > 5 else "").split(",") if k]
    scratch = tempfile.mkdtemp(prefix="pad1197-")
    launcher = os.path.join(scratch, "launch1197.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": card, "emulate_overrides": True,
                   "manufacturers": {"stern": {"write_assets": proj, "extract_output": proj,
                                               "write_original": card}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "", "PAD_TICKET": "",
           "PAD_SLOT": ""}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env,
                                        app_cmd=[sys.executable, launcher])
    print("tree", tree, "server", url.split("?")[0])
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(4)
            for k in kinds:
                webui_shot.api(url, "emulate.set_leave_out", k, True)
            time.sleep(2)
            em = webui_shot.state(url).get("emulate", {})
            print("overrides:", em.get("overrides"), "| assets:", em.get("assets"),
                  "| offer:", [(o["key"], o["on"]) for o in em.get("leave_out_offer") or []])
            page.locator(".emu-ovr").scroll_into_view_if_needed()
            time.sleep(1.5)
            page.screenshot(path=out)
            print("shot", out)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
