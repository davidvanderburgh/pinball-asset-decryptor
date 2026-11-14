"""PAD-1279 proof shot: the Multi-boot tab's Menu settings dialog on a Stern project.

    python scripts/shot_pad1279.py <repo to run> <out.png> [<picture> ...]

Before PAD-1279 the dialog's Look box ends with the SETTINGS card tick; after it, a
Test pictures list sits under that tick (the pictures named on the command line,
as if added with Add test pictures...).  The server runs from <repo> against a
scratch settings folder; the dialog itself is photographed (the shot_pad219.py rig).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad219  # noqa: E402

HOST = r'''
import json, sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import multiboot_panel as mp
from pinball_decryptor.webui import host
TESTS = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad1279_done", False) and hasattr(self, "set_test_pictures"):
        self._pad1279_done = True
        self.set_test_pictures([(p, l) for p, l in TESTS])
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    repo, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    labels = ["Grey card", "Sunset photo", "440 Hz tone"]
    tests = [(os.path.abspath(p), labels[k] if k < len(labels) else "")
             for k, p in enumerate(sys.argv[3:])]
    scratch = tempfile.mkdtemp(prefix="pad1279-")
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump(tests, f)
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "spec": spec})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1"})
    print("repo", repo, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        time.sleep(4)
        webui_shot.api(url, "multiboot.menu_settings")
        md = (webui_shot.state(url)["multiboot"].get("s") or {}).get("md") or {}
        print("tests in the dialog:", [t.get("label") for t in md.get("tests") or []], flush=True)
        shot_pad219.SHOT_H = 1400
        shot_pad219.shoot(url, out, scratch)
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
