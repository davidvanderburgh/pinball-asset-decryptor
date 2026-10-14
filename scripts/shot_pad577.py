"""PAD-577 proof shots: a Stern SAM code update picked on the Stern card.

    python scripts/shot_pad577.py <repo> <out_dir> [--after] [--input <file>]

Serves <repo> on a scratch settings file whose Stern input is the SAM file
(default: Mustang LE 1.45 as a bare, renamed .bin) and writes, under the
same names before and after:

- select_card.png   the Select card tab with that file picked
- extract.png       the Extract tab for it

Nothing is extracted.  Needs Playwright (the user site-packages one) and
the installed Edge.
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
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
INPUT = r"C:\tmp\PAD-577\in\Mustang_LE_1_45.bin"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    src = sys.argv[sys.argv.index("--input") + 1] \
        if "--input" in sys.argv else INPUT
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad577-")
    project = os.path.join(scratch, "Mustang")
    launcher = os.path.join(scratch, "launch577.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_input": src,
                                               "extract_output": project}}}, f)
    print("serving", repo, "input", src, flush=True)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            for tab, name in (("card", "select_card.png"),
                              ("extract", "extract.png")):
                api("ui.select_tab", tab)
                time.sleep(5)
                page.mouse.move(5, 940)
                time.sleep(0.5)
                page.screenshot(path=out(name))
                st = webui_shot.state(url)
                print(tab, "era:", (st.get("shell") or {}).get("mfr", {}).get("era"),
                      "| extract:", {k: (st.get("extract") or {}).get(k)
                                     for k in ("input_label", "capture_cap",
                                               "block_reason")}, flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
