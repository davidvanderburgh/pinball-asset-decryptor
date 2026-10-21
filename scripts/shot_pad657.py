"""PAD-657 proof shot: the Extract log when a card's game program has no sound
decoder the app can find.

    python scripts/shot_pad657.py <repo> <out.png> [card.raw]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of
main for the "before" shot).  Runs a real Audio-only extract of Jurassic Park
LE 1.16 into a scratch project folder; the served app reads the card's game
program as it always does, and then its sound body provider's first two words
are changed (two NOPs) before the app looks at it -- the program a card
carries when it was changed outside the app.  The card itself is only read.
Waits for the extract to finish, then shoots the tab with the log open.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\jurassic_park_le-1_16_0.Release.8G.sdcard.raw"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import locate as L

_real = E._extract_inputs


def _changed(*a, **k):
    out = _real(*a, **k)
    gr = out[0]
    raw = bytearray(open(gr, "rb").read())
    fw = L._FwView(bytes(raw))
    prov = L.locate_all(raw=bytes(raw))["PROV"]
    seg = next(s for s in fw.segs if s["vaddr"] <= prov < s["vaddr"] + s["filesz"])
    off = seg["off"] + prov - seg["vaddr"]
    raw[off:off + 8] = b"\x00\x00\xa0\xe1" * 2
    open(gr, "wb").write(raw)
    return out


E._extract_inputs = _changed
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    card = sys.argv[3] if len(sys.argv) > 3 else CARD
    scratch = tempfile.mkdtemp(prefix="pad657-")
    project = os.path.join(scratch, "Jurassic Park LE 1.16")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "extract_output": project,
                       "extract_options": {"categories": {
                           "audio": True, "video": False,
                           "images": False, "text": False}}}}}, f)
    launcher = os.path.join(scratch, "launch657.py")
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
            if time.time() - t0 > 1200:
                raise SystemExit("the extract never finished")
            time.sleep(2)
        time.sleep(2)
        print("extract took %.0fs" % (time.time() - t0), flush=True)
        print("project holds:", sorted(os.listdir(project))
              if os.path.isdir(project) else None, flush=True)
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
