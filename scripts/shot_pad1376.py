"""PAD-1376 proof shots: the Balls and Coils groups on the JJP Modes tab's form.

    python scripts/shot_pad1376.py <repo> <out_dir> <before|after>

Jersey Jack picked, the Modes tab, Wonka 03.03, its starter multiball mode
(2_multiball.mode) open, the form clipped to its Balls and Coils groups. after also
shoots the coil picker open on "Hold a coil" (<kind>_modes_coil_picker.png), then picks a
hold, its power, its own switch, a start pulse with a shorter ms and 4 balls through the
inputs, checks the mode lines they wrote (EDITS OK) and shoots them (<kind>_modes_coils_filled.png).
Writes <out_dir>/<kind>_modes_balls_coils.png. Needs Playwright (the user
site-packages one) and the installed Edge; the app runs on a scratch APPDATA.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WONKA_ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"


def _clip(page, titles):
    boxes = []
    for g in page.locator(".jjpm-group").all():
        if g.locator(".jjpm-gt").inner_text().strip().lower() in [t.lower() for t in titles]:
            boxes.append(g.bounding_box())
    x0 = min(b["x"] for b in boxes) - 8
    y0 = min(b["y"] for b in boxes) - 8
    x1 = max(b["x"] + b["width"] for b in boxes) + 8
    y1 = max(b["y"] + b["height"] for b in boxes) + 8
    return {"x": max(0, x0), "y": max(0, y0), "width": x1 - x0, "height": y1 - y0}


def main():
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1376-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": WONKA_ISO, "write_original": WONKA_ISO,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 2400})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.jjp_pick_title", "Wonka-v03.03")
            time.sleep(2)
            webui_shot.api(url, "modes.jjp_open", "2_multiball.mode")
            time.sleep(2)
            print("form:", {k: v for k, v in webui_shot.state(url)["modes"]["jjp"]["form"].items()
                            if k.startswith(("multi", "add_", "ball_", "coil_"))})
            page.locator(".jjpm-group").last.scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_balls_coils.png"),
                            clip=_clip(page, ("Balls", "Coils")))
            if kind == "after":
                page.locator('.jjpm-row[data-key="coil_hold"] .jjpm-pick-open').click()
                time.sleep(1)
                page.screenshot(path=os.path.join(out_dir, kind + "_modes_coil_picker.png"),
                                clip=page.locator(".jjpm-picker").bounding_box())
                # drive the new inputs as a user would, and read back what they wrote
                page.locator(".jjpm-picker .jjpm-item", has_text="coil_magnet_left_lane").click()
                time.sleep(1.5)
                row = page.locator('.jjpm-row[data-key="coil_hold"]')
                row.locator("select").select_option("4")
                time.sleep(1.5)
                hold_on = page.locator('.jjpm-row[data-key="coil_hold_on"]')
                hold_on.locator("select").select_option("switches")
                time.sleep(1)
                hold_on.locator(".jjpm-pick-open").click()
                time.sleep(1)
                page.locator(".jjpm-picker .jjpm-item", has_text="switch_target_tv").first.click()
                time.sleep(1)
                page.locator(".jjpm-picker button", has_text="Done").click()
                start = page.locator('.jjpm-row[data-key="coil_start"]')
                start.locator(".jjpm-pick-open").click()
                time.sleep(1)
                page.locator(".jjpm-picker .jjpm-item", has_text="coil_knocker").first.click()
                time.sleep(1.5)
                ms = start.locator("input[type=number]")
                ms.fill("20")
                ms.press("Enter")
                ms.blur()
                time.sleep(1.5)
                page.locator('.jjpm-row[data-key="multiball"] select').select_option("4")
                time.sleep(1.5)
                j = webui_shot.state(url)["modes"]["jjp"]
                got = {k: v for k, v in j["form"].items() if k.startswith(("multi", "add_", "ball_", "coil_"))}
                print("after edits:", got)
                print("check:", j["check"]["problems"])
                want = {"multiball": "4 10", "add_ball": "switch_target_tv 1", "coil_shot": "coil_knocker",
                        "coil_hold": "coil_magnet_left_lane 1000 4", "coil_hold_on": "switch_target_tv",
                        "coil_start": "coil_knocker 20"}
                print("EDITS", "OK" if got == want else "WRONG %r" % want)
                page.locator(".jjpm-group").last.scroll_into_view_if_needed()
                time.sleep(1)
                page.screenshot(path=os.path.join(out_dir, kind + "_modes_coils_filled.png"),
                                clip=_clip(page, ("Balls", "Coils")))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
