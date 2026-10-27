r"""PAD-769 proof shot: the Emulate tab while a Mac builds its emulator container.

    python scripts/shot_pad769.py <app tree> <out.png> before|after

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after"). Start is
pressed for real; the launch it runs is a stand-in for docker/padbox.sh that prints what padbox.sh prints on a
Mac's first Start - "before": the reporter's log, the "building" line and then nothing; "after": the lines the
new padbox.sh printed in a real Docker build here (its step lines and the once-a-minute "still building" line).
The status poll answers what padbox.sh answers while no container exists yet (state=off). Nothing runs in WSL or
Docker.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

BOX = r'''
import sys, time
def say(s):
    sys.stdout.write(s + "\n"); sys.stdout.flush()
say("[box] /Applications/Pinball Asset Decryptor.app/Contents/Resources/tools/spike2_emu is outside Docker's "
    "file sharing; using a copy in /Users/dboeren/Library/Application Support/pinball_decryptor/spike2_emu")
say("[box] building pad-spike2-emu:c2640744224 (first time takes a few minutes)")
if sys.argv[1] == "after":
    for s in ['#0 building with "desktop-linux" instance using docker driver',
              "#5 [1/6] FROM docker.io/library/ubuntu:24.04",
              "#5 DONE 3.4s",
              "#6 [2/6] RUN apt-get update && apt-get install -y --no-install-recommends bash coreutils ...",
              "#6 2.177 Get:9 http://ports.ubuntu.com/ubuntu-ports noble-security/multiverse arm64 Packages",
              "#6 36.53 Get:314 http://ports.ubuntu.com/ubuntu-ports noble-updates/main arm64 "
              "gcc-13-arm-linux-gnueabihf arm64 13.3.0-6ubuntu2~24.04.1cross1 [19.6 MB]",
              "[box] still building the emulator container: 1 min so far",
              "#6 62.43 Preparing to unpack .../0-python3-minimal_3.12.3-0ubuntu2.1_arm64.deb ...",
              "[box] still building the emulator container: 2 min so far",
              "#6 122.8 Setting up libgsm1:arm64 (1.0.22-1build1) ...",
              "[box] still building the emulator container: 3 min so far",
              "#6 139.7 Setting up libgstreamer-plugins-base1.0-0:arm64 (1.24.2-1ubuntu0.5) ..."]:
        say(s)
time.sleep(90)
'''

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
for name in ("_precache_kick", "_select_probe_kick", "_spike3_kick", "_backup_kick", "_setup_check",
             "_reattach_data_disk", "_note_the_runtime_is_a_different_machine"):
    if hasattr(T, name):
        setattr(T, name, lambda self, *a, **k: None)
T._rig_layer_up = lambda self: True
T._source_env = lambda self: ["PAD_CARD=/Users/dboeren/Godzilla Heisei v2.raw"]
T._watch_cmd = lambda self, env: [sys.executable, %(box)r, %(mode)r]
class _Done:
    def __init__(self, out):
        self.stdout, self.stderr, self.returncode = out, b"", 0
def _run(self, cmd, **kw):
    if cmd == ["status.sh"]:
        return _Done(b"state=off\nprocs=0\n")
    return _Done(b"")
T._run = _run
T._popen = lambda self, cmd, **kw: subprocess.Popen(cmd, **kw)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    tree, out, mode = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    scratch = tempfile.mkdtemp(prefix="pad769-")
    box = os.path.join(scratch, "box769.py")
    with open(box, "w", encoding="utf-8") as f:
        f.write(BOX)
    launcher = os.path.join(scratch, "launch769.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree, "box": box, "mode": mode})
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
            time.sleep(2)
            webui_shot.api(url, "emulate.toggle")
            time.sleep(6)
            em = webui_shot.state(url).get("emulate", {})
            print("state:", (em.get("vals") or {}).get("state"), "| tip:", (em.get("state_tip") or "")[:80])
            page.screenshot(path=out)
            print("shot", out)
            webui_shot.api(url, "emulate.toggle")
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
