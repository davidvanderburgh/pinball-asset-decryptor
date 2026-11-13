r"""PAD-1238 proof shot: the Emulate tab during a Spike 3 card's first decrypt.

    python scripts/shot_pad1238.py <app tree> <out.png> before|after

<app tree> is a checkout or a `git archive` export (main for "before", the
ticket branch for "after"). Start is pressed on fallout_le-0_82_0 with the
Spike 3 rig stubbed; the launcher's output is the real output of that tree
in the first minutes of the decrypt: on main one "decrypting" line (s3store's
lines sat in sed's buffer), on the branch the byte meter from PAD-1238's cold
run of the same card. Nothing runs in WSL.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

DECRYPT = "s3launch: decrypting the card into the Spike 3 store (once per card; a few minutes)"
LINES = {
    "before": [DECRYPT],
    "after": [DECRYPT,
              "s3launch:   [s3store] fallout_le-0_82_0_spike3-cd1784f800: key from "
              "/mnt/c/Users/david/.pad/spike3_padkeys.json",
              "s3launch:   [s3store] progress 0 0 11213 -",
              "s3launch:   [s3store] p2 rootfs         4794 files    636.0 MB  new    226.3 MB  (6 s)",
              "s3launch:   [s3store] progress 14 1643 11213 105",
              "s3launch:   [s3store] progress 38 4262 11213 79"],
}

LAUNCHER = r'''
import subprocess, sys
sys.path.insert(0, %(tree)r)
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
emulate_rig.status_cmd = lambda: ["status.sh"]
emulate_rig.spike3_rig_present = lambda: True
emulate_rig.spike3_check_cmd = lambda: ["s3check"]
emulate_rig.spike3_keyfile = lambda *a, **k: None
emulate_rig.spike3_launch_cmd = lambda *a, **k: ["s3launch"]
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda: 0
rigslot.release_claimed = lambda *a, **k: None
rigslot.muted = lambda: True
from pinball_decryptor.webui.tabs import emulate
T = emulate.EmulateTab
for name in ("_precache_kick", "_select_probe_kick", "_backup_kick", "_setup_check",
             "_reattach_data_disk", "_note_the_runtime_is_a_different_machine", "_editions_kick",
             "_which_kick", "_mains_kick", "_reattach_card_store"):
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
def _run(self, cmd, **kw):
    if cmd == ["status.sh"]:
        return _Done(b"state=off\nprocs=0\n")
    if cmd == ["s3check"]:
        return _Done(b"s3check: ok\n")
    return _Done(b"")
T._run = _run
LINES = %(lines)r
EMIT = "import sys, time\nfor l in %%r:\n    print(l, flush=True); time.sleep(0.3)\ntime.sleep(600)\n" %% (LINES,)
def _popen(self, cmd, **kw):
    if cmd == ["s3launch"]:
        return subprocess.Popen([sys.executable, "-c", EMIT], **kw)
    return subprocess.Popen([sys.executable, "-c", "pass"])
T._popen = _popen
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

CARD = r"D:\Pinball\images\Stern\spike3\fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"


def main():
    tree, out = (os.path.abspath(a) for a in sys.argv[1:3])
    which = sys.argv[3]
    scratch = tempfile.mkdtemp(prefix="pad1238-")
    launcher = os.path.join(scratch, "launch1238.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree, "card": CARD, "lines": LINES[which]})
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
            webui_shot.api(url, "emulate.toggle")
            time.sleep(8)
            em = webui_shot.state(url).get("emulate", {})
            print("state:", em.get("state"))
            page.screenshot(path=out)
            print("shot", out)
            try:
                webui_shot.api(url, "emulate.toggle")              # Stop
            except Exception:                                   # noqa: BLE001
                pass
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
