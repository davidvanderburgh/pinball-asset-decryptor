"""PAD-1226 proof shots: a shorter replacement picked on the Video tab, and the
clip's "This clip's length" menu.

    python scripts/shot_pad1226.py <repo> <out_dir> <before|after> <project> <short clip>

Serves <repo> on <project> (a video extract, its .extract_source.json naming
the card; its .staged_changes.json is removed first), opens the Video tab,
right-clicks ATTRACT_LOOP1, picks <short clip> as its replacement (the file
dialog is answered from here) and shoots ``<tag>_pick.png`` a moment later:
on the branch that is the "loop it?" question, which is then answered Yes.
Then it opens the row menu's "This clip's length" submenu and shoots
``<tag>_length_menu.png``.  Needs Playwright (user site-packages) and Edge.
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
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import compat
def _pick(**kw):
    print("[shot1226] file dialog %%r -> %%r" %% (kw.get("title"), %(clip)r), flush=True)
    return %(clip)r
compat.filedialog.askopenfilename = _pick
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

ROW = "ATTRACT_LOOP1"


def main():
    repo, out_dir, tag, project, clip = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                         sys.argv[3], os.path.abspath(sys.argv[4]),
                                         os.path.abspath(sys.argv[5]))
    os.makedirs(out_dir, exist_ok=True)
    side = os.path.join(project, ".staged_changes.json")
    if os.path.exists(side):
        os.remove(side)
    with open(os.path.join(project, ".extract_source.json"), encoding="utf-8") as f:
        card = json.load(f)["input_path"]
    scratch = tempfile.mkdtemp(prefix="pad1226-")
    launcher = os.path.join(scratch, "launch1226.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo, "clip": clip})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_TICKET": "", "PAD_SLOT": ""})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.on("console", lambda m: print("console:", m.type, m.text, flush=True)
                    if m.type in ("error", "warning") else None)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(12)                      # the scan and its probe pass
            row = page.locator(".vid-name", has_text=ROW).first
            row.click()
            time.sleep(2)
            row.click(button="right")
            time.sleep(0.8)
            page.get_by_text("Choose replacement…", exact=True).first.click()
            time.sleep(4)
            page.mouse.move(5, 995)
            page.screenshot(path=os.path.join(out_dir, "%s_pick.png" % tag))
            yes = page.get_by_role("button", name="Yes")
            print("question buttons:", yes.count(), flush=True)
            if yes.count():
                yes.first.click()
                time.sleep(3)
            row.click(button="right")
            time.sleep(0.8)
            page.get_by_text("This clip's length", exact=True).first.hover()
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "%s_length_menu.png" % tag))
            page.keyboard.press("Escape")
            browser.close()
        print("staged:", open(side, encoding="utf-8").read() if os.path.exists(side) else "-",
              flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
