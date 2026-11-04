"""PAD-968 proof shot: a Foo Fighters table patched before the Overlord fork
was followed as a latch says "Patch again" on the Visual Pinball tab, with
what patching again mends.

    python scripts/shot_pad968.py <out_dir> [--after]

Serves THIS checkout on a scratch settings.json holding one preview code,
PAD802_CODE from the environment (``tools/preview_code.py issue --name x
--feature vpx``), and Stern Spike 2. Writes <before_|after_>vpx_foo.png: the
Tables card's JP's Foo Fighters row. The tab's state is the kit's real one on
this PC (~/.pad-vpx.json, Visual Pinball's tables folder, whose Foo Fighters
copy was patched on 2026-10-29). Needs Playwright and the installed Edge.
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
    scratch = tempfile.mkdtemp(prefix="pad968-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    rig = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")
    print("serving", os.path.dirname(HERE), flush=True)
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
            deadline = time.time() + 180
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy") and not st.get("authors_busy") \
                        and not st.get("space_busy"):
                    break
                time.sleep(1)
            st = webui_shot.state(url).get("vpx") or {}
            for t in st.get("tables") or []:
                if "Foo" in (t.get("name") or ""):
                    print("  table:", t.get("name"), t.get("title"), "patched", t.get("patched"),
                          "repatch", t.get("repatch"), flush=True)
            time.sleep(1.5)
            row = page.locator(".vpx-tables").get_by_text("Foo Fighters", exact=False).first
            row.evaluate("el => el.scrollIntoView({block: 'center'})")
            time.sleep(0.6)
            b = row.bounding_box()
            tb = page.locator(".vpx-tables").bounding_box()
            page.screenshot(path=os.path.join(out_dir, pre + "vpx_foo.png"),
                            clip={"x": int(tb["x"]) - 4, "y": max(0, int(b["y"]) - 110),
                                  "width": int(tb["width"]) + 8, "height": 300})
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
