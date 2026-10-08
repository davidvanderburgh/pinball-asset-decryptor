"""PAD-465 proof shot: the Write tab's SD card size control on a Bond Pro 1.06 original
(Stern ships Bond on its 16 GB card, a 15.49 GB image).

    python scripts/shot_pad465.py <repo> <out.png> [<choice>]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot).  The settings copy points the Stern Extract input (the Write tab's
original) at the real james_bond_pro-1_06_0.Release.16G.sdcard.raw (PAD_465_CARD
overrides it) and the project at an empty scratch folder.  *choice* is the SD card size
picked before the shot ("16S" for the smaller 16 GB card); the list is drawn open
(the select's ``size``), because a native drop-down never reaches a page screenshot.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

CARD = os.environ.get("PAD_465_CARD") or (
    r"D:\Pinball\images\Stern\spike2\james_bond_pro-1_06_0.Release.16G.sdcard.raw")


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch465.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_input": CARD,
                                               "extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    choice = sys.argv[3] if len(sys.argv) > 3 else ""
    sys.path.insert(0, repo)
    scratch = tempfile.mkdtemp(prefix="pad465-")
    project = os.path.join(scratch, "Bond Pro 1.06")
    os.makedirs(project)
    # an extract of that card, as Extract records one (no warnings over the tab)
    from pinball_decryptor.core.extract_source import write_extract_source
    write_extract_source(project, CARD)
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("d41d8cd98f00b204e9800998ecf8427e  audio/x.wav\n")
    print("serving", repo, flush=True)
    proc, url = _serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    try:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "write")
            w = {}
            for _ in range(60):
                time.sleep(1)
                w = state().get("write") or {}
                if w.get("card_size_cap"):
                    break
            if choice:
                webui_shot.api(url, "ui.set", "write", "card_size", choice)
                for _ in range(20):
                    time.sleep(1)
                    w = state().get("write") or {}
                    if w.get("card_size_shown") == choice:
                        break
            time.sleep(2)
            w = state().get("write") or {}
            print("options:", [o.get("label") for o in w.get("card_size_options") or []],
                  flush=True)
            print("shown:", repr(w.get("card_size_shown")), flush=True)
            print("note:", w.get("card_size_note"), flush=True)
            n = len(w.get("card_size_options") or [])
            page.evaluate("(n) => { const s = document.getElementById('wr-cardsize');"
                          " if (s) { s.size = n; s.scrollIntoView({block: 'center'}); } }",
                          max(n, 2))
            page.mouse.move(5, 890)
            time.sleep(1.5)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
