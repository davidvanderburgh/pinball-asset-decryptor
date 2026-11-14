r"""PAD-1283 proof shot: the Modes tab's Lights page of a Form mode for the Star Wars ELG 1.10 Spike 3 card.

    python scripts/shot_pad1283.py <app tree> <out png>

shot_pad1282.py's project on the Spike 3 card with one Form mode, on its Lights page: before, the Spike 3 port
carried no lamp layer and no show (the 64-bit runtime's lamp and show features read 32-bit structs), so the
page said the mode's lights stay off and offered none of the game's light shows; after, the lamp layer, the game's
own shows and the inserts are carried and the page offers them. Prints the page's light lines.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1283-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.10.0"}, f)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    slug, _ = MP.new_mode(project, "TRENCH RUN")
    launcher = os.path.join(scratch, "launch1283.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.get_by_text("Lights", exact=True).first.click()
            time.sleep(2.5)
            for line in page.inner_text("body").splitlines():
                low = line.lower()
                if any(w in low for w in ("light", "insert", "show", "sweep", "when it")):
                    print("page:", line.strip()[:220], flush=True)
            for lab in ("When it starts", "When it ends", "When a shot is hit"):
                sel = page.get_by_label(lab)
                if sel.count():
                    opts = sel.first.locator("option").all_inner_texts()
                    print("%s: disabled %s, %d options: %s" % (lab, sel.first.is_disabled(), len(opts), opts[:9]),
                          flush=True)
            page.screenshot(path=out)
            shows = out.replace("_lights", "_shows")
            sec = page.get_by_text("The game's light shows", exact=True)
            if sec.count():
                sec.first.scroll_into_view_if_needed()
                page.mouse.move(900, 680)
                page.mouse.wheel(0, 400)
                time.sleep(1)
            page.screenshot(path=shows)
            print("shot", shows, flush=True)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
