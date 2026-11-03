"""PAD-964 proof shots: the Visual Pinball tab says what starting each title's
game needs of the disk - the card image in the emulator's cache, a copy to
make and the room for it, or no room (the game then reads the image where
it lies, slowly) - and offers to play without caching.

    python scripts/shot_pad964.py <out_dir> [--after]

Serves THIS checkout on a scratch settings.json holding one preview code,
PAD802_CODE from the environment (``tools/preview_code.py issue --name x
--feature vpx``), and Stern Spike 2. Writes <before_|after_>vpx_cards.png:
the setup card's Card images row and the first rows of the Tables card.

The tab's state is the kit's real one on this PC (~/.pad-vpx.json, Visual
Pinball's folder, the card folder, the card cache in WSL). Needs Playwright
and the installed Edge.
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


def main():
    out_dir = os.path.abspath(sys.argv[1])
    pre = "after_" if "--after" in sys.argv else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad964-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    # the kit's own record names an installed app's rig (~/.pad-vpx.json
    # `rig`); the cache check must ask THIS checkout's cardmount.sh
    rig = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase, "PAD_VPX_RIG": rig})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1250})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            if webui_shot.state(url)["shell"]["mfr"].get("era") != "spike2":
                webui_shot.api(url, "ui.set_era", "spike2")
                time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "vpx")
            # the page, then its slow parts (the authors' titles, the cache
            # check over WSL): up to two minutes
            deadline = time.time() + 180
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy") and not st.get("authors_busy") \
                        and not st.get("space_busy"):
                    break
                time.sleep(1)
            st = webui_shot.state(url).get("vpx") or {}
            print("vpx:", json.dumps({k: st.get(k) for k in (
                "library", "message", "card_cache", "space", "space_busy")}, default=str)[:1500], flush=True)
            for t in (st.get("tables") or [])[:8]:
                print("  table:", t.get("name"), t.get("title"), t.get("card"), flush=True)
            time.sleep(1.5)
            # the setup card's Card images row with the first rows of the tables under it
            page.locator(".vpx-tables").scroll_into_view_if_needed()
            time.sleep(0.5)
            top = page.locator("text=Card images").first.bounding_box()
            tables = page.locator(".vpx-tables").bounding_box()
            y0 = max(0, int(top["y"]) - 8) if top else int(tables["y"])
            page.screenshot(path=os.path.join(out_dir, pre + "vpx_cards.png"),
                            clip={"x": int(tables["x"]) - 4, "y": y0, "width": int(tables["width"]) + 8,
                                  "height": min(900, int(tables["y"] + tables["height"]) - y0)})
            # further down, a title whose card is not in the cache (Metallica
            # on this PC): the rows say what its first start copies
            row = page.locator(".vpx-tables").get_by_text("Metallica", exact=False).first
            if row.count():
                # in the middle of the window, not at its bottom edge under the status bar
                row.evaluate("el => el.scrollIntoView({block: 'center'})")
                time.sleep(0.5)
                b = row.bounding_box()
                tb = page.locator(".vpx-tables").bounding_box()
                page.screenshot(path=os.path.join(out_dir, pre + "vpx_cards_copy.png"),
                                clip={"x": int(tb["x"]) - 4, "y": max(0, int(b["y"]) - 150),
                                      "width": int(tb["width"]) + 8, "height": 330})
            # the setup card opened out (Details), its Card images row: the
            # cache's room and the choice to play without caching
            btn = page.locator(".vpx-top").get_by_text("Details", exact=True)
            if btn.count():
                btn.first.click()
                time.sleep(0.8)
            page.locator(".vpx-top").scroll_into_view_if_needed()
            time.sleep(0.5)
            page.locator(".vpx-top").screenshot(path=os.path.join(out_dir, pre + "vpx_setup.png"))
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
