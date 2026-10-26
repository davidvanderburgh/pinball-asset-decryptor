"""PAD-749 proof shots: the Partitions tab on a Spike 2 card, the partition
list shown open, then the last partition it offers picked.

    python scripts/shot_pad749.py <repo> <card.raw> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of main for the "before" shots).  Writes <out_dir>/<prefix>_partitions.png
(the list, drawn open) and <prefix>_partitions_last.png (the last one
picked).  The card is only read.
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

# a native <select> list cannot be photographed open: draw it as a list box
OPEN_LIST = """() => { const s = document.getElementById('pex-part');
  s.size = s.options.length; s.style.height = 'auto'; s.parentElement.style.height = 'auto';
  s.parentElement.style.position = 'relative'; s.parentElement.style.zIndex = 50; }"""


def main():
    repo = os.path.abspath(sys.argv[1])
    card = os.path.abspath(sys.argv[2])
    out_dir = os.path.abspath(sys.argv[3])
    prefix = sys.argv[4]
    scratch = tempfile.mkdtemp(prefix="pad749-")
    launcher = os.path.join(scratch, "launch749.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "partitions")
            time.sleep(1)
            # a card with nothing to browse answers with a message box, which
            # holds the call until it is closed: shoot it as it stands
            import threading
            threading.Thread(target=lambda: webui_shot.api(url, "partitions.open_image", card),
                             daemon=True).start()
            time.sleep(6)
            page.evaluate(OPEN_LIST)
            time.sleep(0.5)
            out = os.path.join(out_dir, "%s_partitions.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            labels = page.evaluate(
                "() => [...document.getElementById('pex-part').options].map(o => o.value)")
            print("partitions:", labels, flush=True)
            if not any("Linux (ext4)" in v for v in labels):
                print("nothing browsable: one shot only", flush=True)
                browser.close()
                return
            page.reload()
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "partitions.select_partition", labels[-1])
            time.sleep(3)
            out = os.path.join(out_dir, "%s_partitions_last.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
