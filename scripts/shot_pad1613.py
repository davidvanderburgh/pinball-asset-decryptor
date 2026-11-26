"""PAD-1613 (PR #47) proof shots: the Test card tab's network settings and the Multi-boot tab's Menu settings dialog,
before and after the test card and the boot menu went on the network with no game running.

    python scripts/shot_pad1613.py <repo> <out_dir> <before|after>

Serves <repo> on scratch settings (Stern picked, the Godzilla LE 1.16 card as the source), ticks Remote access on the
Test card tab, and opens Menu settings on the Multi-boot tab.  After: a Wi-Fi network "Home" saved (the scratch
store, PAD_MENU_WIFI_STORE) and the menu network ticked.  Writes <out_dir>/<kind>_testcard_network.png and
<kind>_multiboot_menu_settings.png.

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1613-")
    store = os.path.join(scratch, "menu_wifi.json")
    if kind == "after":
        sys.path.insert(0, repo)
        os.environ["PAD_MENU_WIFI_STORE"] = store
        from pinball_decryptor.core import menu_network as MN
        assert MN.set_wifi("Home", "a-good-password") == ""
        MN.save(multiboot=True)
        print("saved", MN.saved(), flush=True)
    launcher = os.path.join(scratch, "launch1613.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_input": CARD, "write_original": CARD,
                                               "write_output": scratch}}}, f)
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD_MENU_WIFI_STORE": store})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "testcard")
            time.sleep(3)
            webui_shot.api(url, "testcard.set_network", "ssh", True)
            time.sleep(3)
            page.mouse.move(5, 1090)
            page.screenshot(path=os.path.join(out_dir, "%s_testcard_network.png" % kind))
            webui_shot.api(url, "testcard.set_network", "ssh", False)
            webui_shot.api(url, "ui.select_tab", "multiboot")
            time.sleep(4)
            page.get_by_role("button", name="Menu settings…").first.dispatch_event("click")
            time.sleep(4)
            page.evaluate("""() => { for (const el of document.querySelectorAll('*'))
                if (el.scrollHeight > el.clientHeight + 4 && getComputedStyle(el).overflowY.match(/auto|scroll/))
                    el.scrollTop = el.scrollHeight; }""")       # the dialog's end: the Network box
            time.sleep(1)
            page.mouse.move(5, 1090)
            page.screenshot(path=os.path.join(out_dir, "%s_multiboot_menu_settings.png" % kind))
            browser.close()
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
