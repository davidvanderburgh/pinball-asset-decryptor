"""PAD-219 proof shot: the Jersey Jack Multi-boot tab's Menu settings dialog,
where the menu's volume is set.  The JJP menu's scale was 0-40 with 20 the
default; it is 0-100 now, like Stern's, with 100 playing at what 30 of the
old scale did (the machine's amplifiers run at full while the menu plays).

    python scripts/shot_pad219.py <out.png>

The server runs from THIS tree against a scratch settings folder (no WSL, no
container).  Jersey Jack is picked, the Multi-boot tab shown, 'Menu
settings…' opened over the API, and the modal itself is photographed.
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

#: The window the modal is photographed in: tall enough for all of Menu settings.
SHOT_W, SHOT_H = 1180, 1080


def shoot(url, out, scratch):
    """Playwright when this machine has it (PAD_PWLIB names a pip --target
    folder); otherwise the installed Edge in headless mode."""
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _edge_shot(url, out, scratch)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": SHOT_W, "height": SHOT_H})
        page.goto(url)
        page.wait_for_function("window.__padReady === true", timeout=60000)
        time.sleep(3)
        dlg = page.locator(".mb-dlg-menu")
        (dlg.first if dlg.count() else page).screenshot(path=out)
        browser.close()


def _edge_shot(url, out, scratch):
    import subprocess
    edge = None
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.isfile(p):
            edge = p
            break
    if edge is None:
        raise SystemExit("no playwright and no Edge: nothing to photograph with")
    prof = os.path.join(scratch, "edge")
    os.makedirs(prof, exist_ok=True)
    # no --virtual-time-budget: the page holds a websocket open (PAD-190)
    subprocess.run([edge, "--headless=new", "--disable-gpu",
                    "--user-data-dir=" + prof,
                    "--window-size=%d,%d" % (SHOT_W, SHOT_H),
                    "--screenshot=" + out, url],
                   check=True, timeout=120)


def main():
    out = os.path.abspath(sys.argv[1])
    scratch = tempfile.mkdtemp(prefix="pad219-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        time.sleep(4)
        webui_shot.api(url, "multiboot.menu_settings")
        st = webui_shot.state(url)["multiboot"]
        print("dialog:", st.get("dlg"), "volume:", st.get("s", {}).get("volume"),
              "volume_max:", st.get("w", {}).get("volume_max"), flush=True)
        shoot(url, out, scratch)
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
