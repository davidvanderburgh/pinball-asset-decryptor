"""PAD-659 proof shots: a Macrium Reflect backup of a card (``.mrimgx``) picked
where a card image goes, on the Extract tab and on the Emulate tab.

    python scripts/shot_pad659.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of
main for the "before" shot).  The backup is a stand-in: a few MB of bytes that
are no disk image, under the name the reporter's own carried.  Nothing runs on
the rig (``PAD_UI_NO_RIG``).

  <prefix>_extract.png   the Extract tab with the backup as its input
  <prefix>_emulate.png   the Emulate tab with the backup as the card to run
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
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad659-")
    print("repo", repo, flush=True)
    backup = os.path.join(scratch, "xmencopy", "F44390DA22EE866C-00-00.mrimgx")
    os.makedirs(os.path.dirname(backup))
    with open(backup, "wb") as f:
        f.write(os.urandom(4 << 20))
    project = os.path.join(scratch, "Team America")
    os.makedirs(project)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": backup, "extract_output": project}}},
                  f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "PAD_SLOT": ""}
    launcher = os.path.join(scratch, "launch659.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1');"
                " localStorage.setItem('pad.log.h', '220'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "extract")
            time.sleep(4)
            page.mouse.move(5, 1095)
            page.screenshot(path=os.path.join(out_dir,
                                              prefix + "_extract.png"))
            webui_shot.api(url, "ui.select_tab", "emulate")
            webui_shot.api(url, "ui.set", "emulate", "card", backup)
            time.sleep(4)
            page.mouse.move(5, 1095)
            page.screenshot(path=os.path.join(out_dir,
                                              prefix + "_emulate.png"))
            browser.close()
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
