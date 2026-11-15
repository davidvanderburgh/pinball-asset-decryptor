"""PAD-1319 proof shots: New project for this card, the way DragonRR met it.

    python scripts/shot_pad1319.py <repo> <out_dir> <prefix>

A scratch "EXTRACTED" project holds an extract of a stock Godzilla card; New project last
made a project in another folder ("previous projects").  A Godzilla card named like his,
"Godzilla Premium 1.16 Heisei Custom V2.3 Kaiju Edition.raw", sits in a folder of its own
("GZ 1.16 HEISEI 2.3 PREMIUM") and is picked on the Select card tab.  The New project
window that comes up is shot alone: ``<prefix>_new_project.png``.

The cards are stand-in files of a few bytes that the server recognises by name (the
Spike 2 partition probe is replaced in the served process only).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

HOST = r'''
import os, sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import manufacturer as M
_real = M.detect_game
def _by_name(path, *a, **k):
    name = os.path.basename(path).lower()
    if os.path.abspath(path).lower().startswith(%(scratch)r.lower()):
        if name.startswith("godzilla"):
            return "godzilla"
    return _real(path, *a, **k)
M.detect_game = _by_name
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

STOCK = "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
CARD = "Godzilla Premium 1.16 Heisei Custom V2.3 Kaiju Edition.raw"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = os.path.normpath(tempfile.mkdtemp(prefix="pad1319-"))
    prev = os.path.join(scratch, "GZ HEISEI V2.2B")
    project = os.path.join(prev, "EXTRACTED")
    os.makedirs(os.path.join(project, "audio"))
    cards = os.path.join(scratch, "GZ 1.16 HEISEI 2.3 PREMIUM")
    os.makedirs(cards)
    stock = os.path.join(prev, STOCK)
    card = os.path.join(cards, CARD)
    for p, n in ((stock, 64), (card, 96)):
        with open(p, "wb") as f:
            f.write(b"\0" * n)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": stock, "input_name": STOCK, "size": 64}, f)
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("d41d8cd98f00b204e9800998ecf8427e  audio/x.wav\n")
    sys.path.insert(0, repo)
    from pinball_decryptor.core import project_file
    project_file.save(project_file.anchor_path(project), manufacturer_key="stern",
                      paths={"extract_input": stock, "extract_output": project,
                             "write_assets": project},
                      extract_options={}, stock_image=stock)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "scratch": scratch})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "project_dir": prev,
                   "manufacturers": {"stern": {"extract_input": stock,
                                               "extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", repo, "scratch", scratch, flush=True)
    try:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "card")
            time.sleep(4)
            webui_shot.api(url, "extract.use_recent", "input", card)
            time.sleep(6)
            dlg = page.locator(".modal").last
            shot = os.path.join(out_dir, "%s_new_project.png" % prefix)
            if dlg.count():
                dlg.screenshot(path=shot)
            else:
                print("NO DIALOG - full page shot", flush=True)
                page.screenshot(path=shot)
            print("shot", shot, flush=True)
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
