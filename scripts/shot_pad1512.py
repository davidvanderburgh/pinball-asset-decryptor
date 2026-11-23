"""PAD-1512 proof shots: the JJP mode editor (Modes tab, Godfather 02.03).
    python scripts/shot_pad1512.py <repo> <out_dir> <before|after>
Before: the starter's first mode, the form's last group (Rules from Spike 2).  After: Kiss the Ring,
its Wizard mode and game type group, then its Blocks hat for the game's own modes on a new blocks
mode.  A scratch settings folder: David's own mode folders are never touched.  Needs Playwright
(PAD_PWLIB / the user site) and Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

GF_ISO = r"D:\Pinball\images\JJP\Godfather-v02.03.iso"


def main():
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1512-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": GF_ISO, "write_original": GF_ISO,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            # the title follows the selected card, the Godfather ISO (PAD-1412)
            webui_shot.api(url, "modes.jjp_open", "3_kiss_the_ring.mode" if kind == "after" else "1_example.mode")
            time.sleep(2)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
            group = "Wizard mode and game type" if kind == "after" else "Rules from Spike 2"
            page.get_by_text(group, exact=True).first.evaluate("e => e.scrollIntoView({block: 'start'})")
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_mode_form.png"))
            if kind == "after":
                fn = webui_shot.api(url, "modes.jjp_new", "Wizard Blocks", "blocks")
                fn = fn.get("result", fn) if isinstance(fn, dict) else fn
                prog = {"vars": [{"name": "jobs", "reset": "kept"}], "scripts": [
                    {"hat": {"kind": "played", "mode": "BoxingMode", "when": "ended"}, "do": [
                        {"op": "change", "var": "jobs", "by": {"k": "num", "v": 1}},
                        {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "all_played"}, "b": {"k": "num", "v": 12}},
                         "then": [{"op": "start_mode"}], "else": None}]}]}
                webui_shot.api(url, "modes.jjp_blocks_save", fn, prog)
                time.sleep(3)
                hat = page.get_by_text("When the game", exact=True)
                if hat.count():
                    hat.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                else:                         # the mode's own page: from its top
                    page.locator(".bk-script, .jjpm-mode, h2, h3").first.evaluate("e => e.scrollIntoView({block: 'start'})")
                time.sleep(1)
                add = page.get_by_text("When the game starts or ends one of its modes", exact=True)
                if add.count():                # the palette's new hat, added as a script
                    add.first.click()
                    time.sleep(2)
                    added = page.get_by_text("When the game", exact=True)
                    if added.count():
                        added.last.evaluate("e => e.scrollIntoView({block: 'center'})")
                    time.sleep(1)
                page.screenshot(path=os.path.join(out_dir, kind + "_blocks.png"))
                print("blocks hat shown:", bool(hat.count()), fn)
            print("page errors:", errors)
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
