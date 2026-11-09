r"""PAD-1071 proof shots: the Emulate tab's Sound and video log, and the log window itself.

    python scripts/shot_pad1071.py <app tree> <out dir> [before|after]

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after"). Serves it on a
scratch copy of the Deadpool Pro 1.16 project (C:\tmp\Pinball\Deadpool Pro: its sound requests and video manifest,
nothing written into it) with the card picked on the Emulate tab; nothing runs on the rig. Writes
<out dir>\<before|after>_emulate.png (the tab) and, on a tree that has the window, <out dir>\after_log.png: the log
page with the events a real Deadpool Pro run wrote (sounds_seen / clips_seen, copied from the proof run's files when
PAD1071_EVENTS names their folder, else a few lines typed here in the same shape).
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\deadpool_pro-1_16_0.Release.8G.sdcard.raw"
PROJECT = r"C:\tmp\Pinball\Deadpool Pro"

LAUNCHER = r'''
import subprocess, sys, os
sys.path.insert(0, %(tree)r)
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
emulate_rig.status_cmd = lambda: ["status.sh"]
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda: 0
from pinball_decryptor.webui.tabs import emulate
T = emulate.EmulateTab
for name in ("_precache_kick", "_select_probe_kick", "_spike3_kick", "_backup_kick", "_setup_check",
             "_reattach_data_disk", "_note_the_runtime_is_a_different_machine", "_editions_kick",
             "_which_kick", "_mains_kick", "_docker_check"):
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

#: the events, in the playfield's shape, when no proof run's files are named
TYPED_SOUNDS = [(0.0, 1001), (0.4, 1060), (2.1, 612), (3.0, 1001), (5.5, 74)]
TYPED_CLIPS = [(1.2, "CloneMultiballStart"), (4.6, "CloneMultiball_ModeTotal")]


def _project(scratch):
    """A copy of the parts of the project the tabs read (no audio/video bytes but the names)."""
    dst = os.path.join(scratch, "Deadpool Pro")
    os.makedirs(os.path.join(dst, "audio"))
    os.makedirs(os.path.join(dst, "video"))
    for name in ("sound_requests.tsv", "sound_test_names.csv", ".extract_source.json"):
        if os.path.isfile(os.path.join(PROJECT, name)):
            shutil.copyfile(os.path.join(PROJECT, name), os.path.join(dst, name))
    shutil.copyfile(os.path.join(PROJECT, "video", "manifest.txt"), os.path.join(dst, "video", "manifest.txt"))
    for name in os.listdir(os.path.join(PROJECT, "audio")):
        open(os.path.join(dst, "audio", name), "wb").close()
    for name in os.listdir(os.path.join(PROJECT, "video")):
        if name != "manifest.txt":
            open(os.path.join(dst, "video", name), "wb").close()
    return dst


def _events(ctl, project):
    """sounds_seen_0.jsonl / clips_seen_0.jsonl beside the volume file, as a run leaves them."""
    os.makedirs(ctl, exist_ok=True)
    src = os.environ.get("PAD1071_EVENTS")
    if src:
        for name in ("sounds_seen_0.jsonl", "clips_seen_0.jsonl", "clip_names_0.json"):
            if os.path.isfile(os.path.join(src, name)):
                shutil.copyfile(os.path.join(src, name), os.path.join(ctl, name))
        return
    t0 = time.time() - 60
    with open(os.path.join(ctl, "sounds_seen_0.jsonl"), "w", encoding="utf-8") as f:
        for dt, req in TYPED_SOUNDS:
            f.write(json.dumps({"t": round(t0 + dt, 3), "request": req, "n": 0}) + "\n")
    with open(os.path.join(ctl, "clips_seen_0.jsonl"), "w", encoding="utf-8") as f:
        for dt, name in TYPED_CLIPS:
            f.write(json.dumps({"t": round(t0 + dt, 3), "rel": "video/%s.mov" % name, "name": name,
                                "path": "./x", "switch": ""}) + "\n")


def main():
    tree, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    tag = sys.argv[3] if len(sys.argv) > 3 else "after"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1071-")
    project = _project(scratch)
    launcher = os.path.join(scratch, "launch1071.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    _events(os.path.join(scratch, "cfg", "pinball_decryptor"), project)   # beside the volume file
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
            webui_shot.api(url, "ui.set", "emulate", "card", CARD)
            time.sleep(4)
            page.mouse.move(5, 990)
            shot = os.path.join(out_dir, "%s_emulate.png" % tag)
            page.screenshot(path=shot)
            print("shot", shot)
            if not page.get_by_text("Sound and video log").count():
                print("this tree has no Sound and video log")
                browser.close()
                return
            log = browser.new_page(viewport={"width": 760, "height": 620})
            log.goto(url.split("?")[0].rstrip("/") + "/static/js/tabs/emulate_log.html?" + url.split("?", 1)[1])
            log.wait_for_selector(".elog-row", timeout=30000)
            time.sleep(2)
            print("log rows:", log.locator(".elog-row").count())
            shot = os.path.join(out_dir, "%s_log.png" % tag)
            log.screenshot(path=shot)
            print("shot", shot)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
