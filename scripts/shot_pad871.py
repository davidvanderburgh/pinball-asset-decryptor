r"""PAD-871 proof shot: the Emulate tab's Save states panel as a Linux desktop sees it.

    python scripts/shot_pad871.py <app tree> <out.png> root|noroot

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after"). The tab is
told it runs on Linux (its own ``sys`` only; the rest of the app stays on Windows). ``root`` is a desktop where the
app reaches root without a password (the app run as root, or a sudo that asks none, as in the Docker image);
``noroot`` is one where it cannot. A main tree has no such question and shows its Linux panel either way. A rig
command that lists the slots answers with the listing a real save gave in PAD-871's proof run (Godzilla Pro 1.16,
started and saved through `sudo -n` on the native-Linux path); nothing runs in WSL.
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
import subprocess, sys, types
sys.path.insert(0, %(tree)r)
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
emulate_rig.status_cmd = lambda: ["status.sh"]
if hasattr(emulate_rig, "savestates_possible"):
    emulate_rig.savestates_possible = lambda: %(root)r
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda: 0
from pinball_decryptor.webui.tabs import emulate
class _Linux(types.ModuleType):
    platform = "linux"
    def __getattr__(self, name):
        return getattr(sys, name)
emulate.sys = _Linux("sys")
T = emulate.EmulateTab
for name in ("_precache_kick", "_select_probe_kick", "_spike3_kick", "_backup_kick", "_setup_check",
             "_reattach_data_disk", "_note_the_runtime_is_a_different_machine", "_editions_kick",
             "_which_kick", "_mains_kick", "_docker_check"):
    if hasattr(T, name):
        setattr(T, name, lambda self, *a, **k: None)
T._card_game = lambda self: "godzilla_pro"
class _Done:
    def __init__(self, out):
        self.stdout, self.stderr, self.returncode = out, b"", 0
LISTING = %(listing)r
def _run(self, cmd, **kw):
    if cmd == ["status.sh"]:
        return _Done(b"state=off\nprocs=0\n")
    if "slots.sh" in " ".join(map(str, cmd)) and cmd[-1] == "list":
        return _Done(LISTING.encode())
    return _Done(b"")
T._run = _run
T._popen = lambda self, cmd, **kw: subprocess.Popen([sys.executable, "-c", "pass"])
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

#: slots.sh list, as the proof run's save left it (one slot, 43 MB)
LISTING = ("slot|godzilla_pro/pad871test|44875417|godzilla_pro|PAD-871 proof|1793385579\n"
           "total|44875417\nfree|65712999999\n")


def main():
    tree, out, mode = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    scratch = tempfile.mkdtemp(prefix="pad871-")
    launcher = os.path.join(scratch, "launch871.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree, "listing": LISTING, "root": mode == "root"})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "", "PAD_TICKET": "", "PAD_SLOT": ""}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env, app_cmd=[sys.executable, launcher])
    print("tree", tree, "server", url.split("?")[0], "mode", mode)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(2)
            # the slots, as Refresh reads them (a main tree's Linux panel refuses)
            webui_shot.api(url, "emulate.slots_refresh")
            time.sleep(3)
            em = webui_shot.state(url).get("emulate", {})
            print("slots_enabled:", em.get("slots_enabled"), "| sum:", em.get("slots_sum"),
                  "| rows:", len(em.get("slots") or []))
            page.locator(".emu-states").scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=out)
            print("shot", out)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
