"""PAD-467 proof shot: the Write tab's SD card size control and, under it, "Make the image as
small as it can be", on a Godzilla Pro 1.16 original (Stern's 8 GB card).

    python scripts/shot_pad467.py <repo> <out.png> [<choice> [fit]]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot).  The settings copy points the Stern Extract input (the Write tab's
original) at the real godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw (PAD_467_CARD
overrides it) and the project at an empty scratch folder.  *choice* is the SD card size
picked before the shot ("" for the original's own size, "16G" ...); "fit" ticks the new
option (a tree without it just shows the control as it was).
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

CARD = os.environ.get("PAD_467_CARD") or (
    r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch467.py")
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
    fit = len(sys.argv) > 4 and sys.argv[4] == "fit"
    sys.path.insert(0, repo)
    scratch = tempfile.mkdtemp(prefix="pad467-")
    project = os.path.join(scratch, "Godzilla Pro 1.16")
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
            if fit:
                webui_shot.api(url, "ui.set", "write", "card_fit", True)
                for _ in range(20):
                    time.sleep(1)
                    w = state().get("write") or {}
                    if w.get("card_fit"):
                        break
            time.sleep(2)
            w = state().get("write") or {}
            print("options:", [o.get("label") for o in w.get("card_size_options") or []],
                  flush=True)
            print("shown:", repr(w.get("card_size_shown")), flush=True)
            print("note:", w.get("card_size_note"), flush=True)
            print("fit cap/on:", w.get("card_fit_cap"), w.get("card_fit"), flush=True)
            print("fit label:", w.get("card_fit_label"), flush=True)
            print("build path:", w.get("build_path"), flush=True)
            page.evaluate("() => { const s = document.getElementById('wr-cardsize');"
                          " if (s) s.scrollIntoView({block: 'center'}); }")
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
