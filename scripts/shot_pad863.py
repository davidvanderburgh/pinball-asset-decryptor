"""PAD-863 proof: what Emulate says while it prepares a project's edits, first time and next.

    python scripts/shot_pad863.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  A scratch project of the Godzilla Pro card, "Apply my replaced assets"
ticked, the rig stood in (PAD_UI_NO_RIG).  The override build is stood in too: it says
what a real one says first ("Extracting image.bin") and holds there for a while, so the
State line can be photographed mid-build, then leaves a set the next Start can patch.

  <prefix>_emulate_first_start.png   the first Start, mid-build (no set staged yet)
  <prefix>_emulate_next_start.png    the next Start after an edit, mid-build (a set to patch)
"""

import json
import os
import shutil
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = (r"C:\Users\david\Documents\development\pinball-asset-decryptor\images\Stern\spike2"
        r"\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
HOLD = 12.0

LAUNCHER = r'''
import os, sys, time
sys.path.insert(0, @REPO@)
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda *a, **k: 1
from pinball_decryptor.plugins.stern import engine
def write_overrides(card, assets, out, log=None, progress=None, **kw):
    log("Extracting firmware (8.1 MB)...")
    log("Extracting image.bin (2010 MB)...")
    progress(3, 100, "Reading image.bin")
    time.sleep(@HOLD@)
    st = os.stat(card)
    os.makedirs(out, exist_ok=True)
    engine._write_override_manifest(out, {
        "version": engine.OVERRIDE_VERSION, "generation": "1",
        "card": {"path": os.path.abspath(card), "size": st.st_size,
                 "mtime": int(st.st_mtime)},
        "assets": os.path.abspath(assets), "files": []})
    return (1, 0, 0, 0), None, None, [("/godzilla_pro/image.bin", 2010000000)]
engine.write_overrides = write_overrides
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def make_project(scratch):
    proj = os.path.join(scratch, "Godzilla Extract")
    os.makedirs(os.path.join(proj, "audio"))
    with open(os.path.join(proj, "audio", "idx0001.wav"), "wb") as f:
        f.write(b"RIFF")
    with open(os.path.join(proj, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("audio/idx0001.wav\t00000000000000000000000000000000\n")
    with open(os.path.join(proj, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.16"}, f)
    return proj


def _button(url):
    return (((webui_shot.state(url).get("emulate") or {}).get("run_btn") or {})
            .get("label") or "")


def _start_and_shoot(url, page, out, project):
    webui_shot.api(url, "emulate.toggle")
    time.sleep(HOLD / 2)
    st = webui_shot.state(url)
    print("state:", (st.get("emulate") or {}).get("vals", {}).get("state"), flush=True)
    page.evaluate("""() => { const ls = document.querySelectorAll('.line');
        if (ls.length) ls[ls.length - 1].scrollIntoView({block: 'end'}); }""")
    time.sleep(0.5)
    page.screenshot(path=out)
    print("shot", out, flush=True)
    t0 = time.time()
    while time.time() - t0 < 60:
        b = _button(url)
        if b and "Cancel" not in b and "…" not in b and "Stop" not in b:
            break
        time.sleep(1)
    lines = page.evaluate(
        "Array.from(document.querySelectorAll('.line')).map(e => e.textContent)")
    for ln in lines[-12:]:
        print("   ", ln[:220], flush=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad863-")
    project = make_project(scratch)
    launcher = os.path.join(scratch, "launch863.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER.replace("@REPO@", repr(repo)).replace("@HOLD@", repr(HOLD)))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": CARD, "emulate_overrides": True,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    tmp = os.path.join(scratch, "tmp")      # %TEMP%\spike2_overrides goes here
    os.makedirs(tmp)
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "TEMP": tmp, "TMP": tmp}
    proc, url = webui_shot.start_server(settings, scratch,
                                        app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.add_init_script("localStorage.setItem('pad.log.open', '1');"
                                 "localStorage.setItem('pad.log.h', '300');")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(3)
            _start_and_shoot(url, page, os.path.join(
                out_dir, "%s_emulate_first_start.png" % prefix), project)
            # an edit since: the project's sound written over
            time.sleep(1.5)
            with open(os.path.join(project, "audio", "idx0001.wav"), "ab") as f:
                f.write(b"edit")
            _start_and_shoot(url, page, os.path.join(
                out_dir, "%s_emulate_next_start.png" % prefix), project)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                    # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
