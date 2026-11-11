r"""PAD-1147 proof shot: the Emulate tab's Save states panel on a Spike 3 card.

    python scripts/shot_pad1147.py <app tree> <out.png> <listings.txt>

<app tree> is a checkout or a `git archive` export (main for "before", the
ticket branch for "after"). The tab has a pokemon_le Spike 3 card picked and
the Spike 3 rig present. Every rig command is answered from <listings.txt>:
the real `slots.sh list` of this PC's Spike 2 rig, then a line "===", then
the real `s3launch.sh --slots list` of its Spike 3 rig (two Pokemon slots
saved in PAD-1147's proof run). Main asks slots.sh, so it lists Spike 2's;
the branch asks the Spike 3 rig. Nothing runs in WSL.
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
emulate_rig.spike3_rig_present = lambda: True
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda: 0
from pinball_decryptor.webui.tabs import emulate
T = emulate.EmulateTab
emulate._slots_here = lambda: True
for name in ("_precache_kick", "_select_probe_kick", "_backup_kick", "_setup_check",
             "_reattach_data_disk", "_note_the_runtime_is_a_different_machine", "_editions_kick",
             "_which_kick", "_mains_kick"):
    if hasattr(T, name):
        setattr(T, name, lambda self, *a, **k: None)
def _kick(self):
    path = self._card()
    self._spike3_probed = path
    self._post(self._spike3_apply, path, True, "the boot partition is labelled SPIKE3")
T._spike3_kick = _kick
CARD = %(card)r
_show = T.on_show
def _on_show(self):
    if not self._card():
        self.emulate_card_var.set(CARD)
        self._spike3_kick()
    return _show(self)
T.on_show = _on_show
class _Done:
    def __init__(self, out):
        self.stdout, self.stderr, self.returncode = out, b"", 0
S2, S3 = %(s2)r, %(s3)r
def _run(self, cmd, **kw):
    j = " ".join(map(str, cmd))
    if cmd == ["status.sh"]:
        return _Done(b"state=off\nprocs=0\n")
    if "--slots" in j and cmd[-1] == "list":
        return _Done(S3.encode())
    if "slots.sh" in j and cmd[-1] == "list":
        return _Done(S2.encode())
    return _Done(b"")
T._run = _run
T._popen = lambda self, cmd, **kw: subprocess.Popen([sys.executable, "-c", "pass"])
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

CARD = r"D:\Pinball\images\Stern\spike3\pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"


def main():
    tree, out, lst = (os.path.abspath(a) for a in sys.argv[1:4])
    s2, s3 = open(lst, encoding="utf-8").read().split("===\n", 1)
    scratch = tempfile.mkdtemp(prefix="pad1147-")
    launcher = os.path.join(scratch, "launch1147.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree, "s2": s2, "s3": s3, "card": CARD})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "", "PAD_TICKET": "", "PAD_SLOT": ""}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env, app_cmd=[sys.executable, launcher])
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
            webui_shot.api(url, "emulate.slots_refresh")     # what the status poll does
            time.sleep(3)
            em = webui_shot.state(url).get("emulate", {})
            print("card:", em.get("card"), "| sum:", em.get("slots_sum"),
                  "| rows:", [r.get("iid") for r in (em.get("slots") or [])])
            page.locator(".emu-states").scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=out)
            print("shot", out)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
