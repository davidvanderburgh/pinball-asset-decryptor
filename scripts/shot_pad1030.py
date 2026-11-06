"""PAD-1030 proof shot: Try it on a blocks mode with 13 clips of its own.

    python scripts/shot_pad1030.py <repo> <out.png>

Serves <repo>, with the mode maker's preview on, on a scratch project made from the James Bond LE 1.06 card, with a
blocks mode carrying 13 clips (crem1..crem12, then background2 looping behind the HUD when the mode starts), shows it
and presses Try it. The hand-off to the Emulate tab is stubbed (nothing runs on the rig). Before (v1.351.0) the mode is
"To fix: 13 clips of its own: 12 at most", yet Try it goes ahead and assets.json carries 12 (background2 left out);
after, the limit is 32: the mode is Ready to build and assets.json carries all 13 (the rig prints the count).

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\james_bond_le-1_06_0.Release.16G.sdcard.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import modes_tryit
modes_tryit.TryItMixin._try_fn = lambda self, prepare: (True, "")     # never the rig
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _mode(repo, project):
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    print("block_modes from", BM.__file__, flush=True)
    slug, _p = BM.new_blocks_mode(project, "Diamond Death Threat", shots=["Left orbit"])
    folder = os.path.join(project, "modes", slug)
    prog = BM.load(project, slug)
    prog["clips"] = [{"name": "crem%d" % i, "file": "crem%d.mp4" % i} for i in range(1, 13)]
    prog["clips"].append({"name": "background2", "file": "background2.mp4"})
    for c in prog["clips"]:
        with open(os.path.join(folder, c["file"]), "wb") as f:
            f.write(b"x")
    for s in prog["scripts"]:
        if (s.get("hat") or {}).get("kind") == "mode_start":
            s["do"] = [{"op": "clip", "clip": "crem11", "where": "full"},
                       {"op": "clip", "clip": "background2", "where": "loop"}]
    BM.save(project, slug, prog)
    with open(os.path.join(folder, "assets.json"), encoding="utf-8") as f:
        print("assets.json clips:", len(json.load(f).get("clips") or {}), flush=True)
    return slug


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1030-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.06.0"}, f)
    slug = _mode(repo, project)
    launcher = os.path.join(scratch, "launch1030.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1"})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(8)
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(4)
            print("tryit ->", webui_shot.api(url, "modes.tryit"), flush=True)
            time.sleep(3)
            page.mouse.move(5, 990)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
