"""PAD-659 proof shot: a file off the card's own boot partition
(``D:\\stern-spike2.dtb``) picked as the card to run on the Emulate tab.

    python scripts/shot_pad659_dtb.py <repo> <out.png>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of
main for the "before" shot).  The file is a stand-in: a device-tree header and
zeros, under the name the reporter picked.  Nothing runs on the rig
(``PAD_UI_NO_RIG``).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad659d-")
    print("repo", repo, flush=True)
    dtb = os.path.join(scratch, "D", "stern-spike2.dtb")
    os.makedirs(os.path.dirname(dtb))
    with open(dtb, "wb") as f:
        f.write(b"\xd0\x0d\xfe\xed" + bytes(47941))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"},
                  f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "PAD_SLOT": ""}
    launcher = os.path.join(scratch, "launch659d.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write("import sys; sys.path.insert(0, %r)\n"
                "from pinball_decryptor.webui import host\n"
                "sys.argv = ['host'] + sys.argv[1:]\n"
                "sys.exit(host.main())\n" % repo)
    proc, url = webui_shot.start_server(settings, scratch,
                                        app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1');"
                " localStorage.setItem('pad.log.h', '160'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            webui_shot.api(url, "ui.set", "emulate", "card", dtb)
            time.sleep(4)
            page.mouse.move(5, 995)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
