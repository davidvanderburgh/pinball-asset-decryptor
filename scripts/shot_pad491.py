"""PAD-491 proof: Emulate's Start, edits on, over a card whose game program has a HOLE.

    python scripts/shot_pad491.py <repo> <out_dir> <prefix> <card> <project>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for
the "before" shot).  <card> is a Godzilla card whose ``godzilla_le/game`` has a block of
zeros left unallocated (``fallocate --dig-holes`` on a copy: a Linux cp leaves the same),
and <project> a project extracted from it whose only edits are the scene lines PAD sets
back to their words.  The project is copied to a scratch folder and recorded as
extracted from <card>; "Apply my replaced assets" is ticked and Start pressed with the
rig stood in (PAD_UI_NO_RIG: nothing reaches WSL, no game is started).  The server's
temp folder is a scratch one, so the override set it stages is not the one David's own
Emulate tab keeps in %TEMP%.

  <prefix>_emulate.png   once the preparation has ended: refused beside the opt-in
                         (before) or the set built and applied (after)
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
# the rig stood in: Start goes as far as the preparation and no further
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda *a, **k: 1
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

DONE = ("could not be prepared", "will be applied on top of the card", "nothing to apply")


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    card = os.path.abspath(sys.argv[4])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad491-")
    project = os.path.join(scratch, "Godzilla")
    shutil.copytree(os.path.abspath(sys.argv[5]), project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card),
                   "card_version": "1.16"}, f)
    # the Extract baseline Emulate asks for before it applies anything (one
    # unchanged file: the edits are the text manifest's)
    sys.path.insert(0, repo)
    from pinball_decryptor.core.checksums import md5_file
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("text/strings.tsv\t%s\n"
                % md5_file(os.path.join(project, "text", "strings.tsv")))
    tmp = os.path.join(scratch, "tmp")
    os.makedirs(tmp)
    print("repo", repo, "project", project, flush=True)
    launcher = os.path.join(scratch, "launch491.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": card, "emulate_overrides": True,
                   "manufacturers": {"stern": {"extract_input": card,
                                               "extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "TEMP": tmp, "TMP": tmp}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(3)
            webui_shot.api(url, "emulate.toggle")
            t0, said = time.time(), ""
            while time.time() - t0 < 120:
                time.sleep(1)
                with open(os.path.join(scratch, "server.log"), encoding="utf-8",
                          errors="replace") as f:
                    said = f.read()
                if any(d in said for d in DONE):
                    break
            time.sleep(4)
            st = webui_shot.state(url)
            vals = (st.get("emulate") or {}).get("vals", {})
            print("state", vals.get("state"), "| ovr_hint", vals.get("ovr_hint"),
                  "| refused", vals.get("ovr_refused"), flush=True)
            for ln in said.splitlines():
                if "[emulate]" in ln and any(k in ln for k in (
                        "prepar", "traced", "Built", "Override", "applied", "rig")):
                    print("   ", ln[:240], flush=True)
            out = os.path.join(out_dir, "%s_emulate.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
    print("scratch", scratch, flush=True)


if __name__ == "__main__":
    main()
