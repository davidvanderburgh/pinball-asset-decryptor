"""PAD-632 proof: the Emulate tab's Start/Stop button while nothing runs on the
main rig but a library sweep's card copier (rigbatch's cardstage.sh `cache`,
``cardmount.sh <card> --cache-now``) is filling the card cache.

    python scripts/shot_pad632.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of
main for the "before" shot).  The tab's REAL status poll runs (no
``PAD_UI_NO_RIG``) against rig 0, read-only; no card is picked, so nothing is
pre-cached and nothing is started.  The rig's own answer (status.sh) is
printed beside the shot.

  <prefix>_emulate.png   the Emulate tab, its Status panel and the one button
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


def rig_status(repo):
    sys.path.insert(0, repo)
    from pinball_decryptor.core import runtime
    from pinball_decryptor.webui import emulate_core as e
    runtime.status(refresh=True)     # route to PAD-Runtime as the app does
    os.environ["PAD_EMU_DIR"] = os.path.join(repo, "tools", "spike2_emu")
    r = subprocess.run(e.status_cmd(), capture_output=True, text=True,
                       timeout=60)
    return r.stdout


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad632-")
    print("repo", repo, flush=True)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"},
                  f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "PAD_SLOT": "",
           "PAD_EMU_DIR": os.path.join(repo, "tools", "spike2_emu")}
    launcher = os.path.join(scratch, "launch632.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write("import sys; sys.path.insert(0, %r)\n"
                "from pinball_decryptor.webui import host\n"
                "sys.argv = ['host'] + sys.argv[1:]\n"
                "sys.exit(host.main())\n" % repo)
    proc, url = webui_shot.start_server(settings, scratch,
                                        app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1350})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            # until the rig's first status answers (WSL start), then a few polls
            t0 = time.time()
            while time.time() - t0 < 180:
                time.sleep(2)
                if page.locator("text=/\d+ running/").count():
                    break
            time.sleep(10)
            page.mouse.move(5, 1345)
            print("--- status.sh, rig 0, at the shot ---\n" + rig_status(repo),
                  flush=True)
            out = os.path.join(out_dir, "%s_emulate.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
