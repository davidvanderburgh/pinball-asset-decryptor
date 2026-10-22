"""PAD-674 proof shot: the Extract log on a card whose game program keys its
sounds through the machine's CPU board (Jurassic Park LE 1.13).

    python scripts/shot_pad674.py <repo> <out.png> <card.raw>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of
main for the "before" shot).  Runs a real Audio-only extract of the card into
a scratch project folder and shoots the tab with the log open once it is
done.  The card is only read.  The card itself (a user's) is never committed.
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
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    card = os.path.abspath(sys.argv[3])
    scratch = tempfile.mkdtemp(prefix="pad674-")
    project = os.path.join(scratch, "Jurassic Park 1.13")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "extract_output": project,
                       "extract_options": {"categories": {
                           "audio": True, "video": False,
                           "images": False, "text": False}}}}}, f)
    launcher = os.path.join(scratch, "launch674.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "extract")
        for k in ("video", "images", "text"):
            webui_shot.api(url, "ui.set", "extract", "cat_" + k, False)
        webui_shot.api(url, "ui.set", "extract", "cat_audio", True)
        time.sleep(2)
        webui_shot.api(url, "extract.start")
        t0 = time.time()
        time.sleep(3)
        while webui_shot.state(url)["shell"].get("running"):
            if time.time() - t0 > 3600:
                raise SystemExit("the extract never finished")
            time.sleep(2)
        time.sleep(2)
        print("extract took %.0fs" % (time.time() - t0), flush=True)
        names = sorted(os.listdir(project)) if os.path.isdir(project) else None
        print("project holds:", names, flush=True)
        audio = os.path.join(project, "audio")
        if os.path.isdir(audio):
            print("sounds:", len([n for n in os.listdir(audio) if n.endswith(".wav")]), flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1');"
                " localStorage.setItem('pad.log.h', '330'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
