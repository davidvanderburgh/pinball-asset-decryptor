"""PAD-205 proof shot: the Emulate tab right after Browse picks a card that is
NOT the project's, with "Apply my replaced assets on top" ticked beforehand.

    python scripts/shot_pad205.py <out.png>

Same scratch project as ``shot_pad199.py`` (no WSL, no rig): the tab starts on
the project's own card with the Apply box ticked, then Browse is answered
through the page's own file dialog with a stock card from elsewhere.
"""

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402
from shot_pad199 import _touch  # noqa: E402


def _reply(url, mid, value):
    base = url.split("/?")[0]
    token = url.split("t=")[1].split("&")[0]
    req = urllib.request.Request(
        base + "/api/reply?t=" + token,
        data=json.dumps({"id": mid, "v": value}).encode(),
        headers={"Content-Type": "application/json", "X-PAD-Token": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    out = os.path.abspath(sys.argv[1])
    scratch = tempfile.mkdtemp(prefix="pad205-")
    cards = os.path.join(scratch, "Pinball RAW Images")
    source = os.path.join(cards, "Heisei", "Godzilla Premium 1.16 Heisei "
                                             "Custom V1.9 Orchestral "
                                             "Edition.raw")
    stock = os.path.join(cards, "godzilla_le-1_16_0_spike2.Release.8G."
                                "sdcard.raw")
    _touch(source)
    _touch(stock)
    project = os.path.join(scratch, "Orchestral Extracted")
    os.makedirs(project)
    from pinball_decryptor.core import extract_source, project_file
    extract_source.write_extract_source(project, source)
    paths = {"extract_input": source, "extract_output": project,
             "write_output": "", "write_original": source,
             "write_assets": project}
    project_file.save(project_file.anchor_path(project),
                      manufacturer_key="stern", paths=paths,
                      extract_options={},
                      extra={"emulate_card": source,
                             "emulate_overrides": True})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": source, "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch,
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "emulate")
        time.sleep(2)
        st = webui_shot.state(url)["emulate"]
        print("before browse: overrides", st.get("overrides"), flush=True)
        t = threading.Thread(
            target=lambda: webui_shot.api(url, "emulate.browse"),
            daemon=True)
        t.start()
        mid = None
        for _ in range(200):
            opened = (webui_shot.state(url).get("modals") or {}).get("open")
            if opened:
                mid = opened[0]["id"]
                break
            time.sleep(0.05)
        if mid is None:
            raise SystemExit("the file dialog never opened")
        print("reply", _reply(url, mid, stock), flush=True)
        t.join(30)
        time.sleep(3)
        st = webui_shot.state(url)["emulate"]
        print("after browse: card", st.get("card"), "| overrides",
              st.get("overrides"), "| which",
              json.dumps(st.get("which"))[:300], flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
