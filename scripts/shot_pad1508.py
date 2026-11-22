"""PAD-1508 proof shots: Spike 2's rules in the Modes tab's JJP and Spooky form.

    python scripts/shot_pad1508.py <repo> <out_dir> <before|after>

Opens Wonka 03.03 (JJP) and Scooby-Doo (Spooky) in the Modes tab, the first starter mode in the
form editor, and photographs the end of the form: before, it ends at Coils; after, the "Rules from
Spike 2" section follows, with a few rules filled in (per-shot points on two lines, a rising ladder,
a countdown sound, a chase).  Writes <out_dir>/<kind>_jjp_rules.png and <kind>_spooky_rules.png.
Needs Playwright (the user site-packages one) and the installed Edge.  The app runs on a scratch
APPDATA, so the mode folders it edits are scratch copies of the starters.
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

TITLES = {
    "jjp": (r"D:\Pinball\images\JJP\Wonka-v03.03.iso", "jjp", [
        ("shot_points", "switch_target_tv 2000000\nswitch_ramp_left_made 5000000"),
        ("points_ladder", "rising"), ("sound_at", "10 se_Fanfare_GT_1"), ("lamp_pattern", "chase"),
        ("start_max", "2")]),
    "spooky": (r"D:\Pinball\images\Spooky\v2025.12.01.09.scooby", "spk", [
        ("shot_points", "right_sling 500000\nmiddle_sling 1000000"),
        ("points_ladder", "rising"), ("sound_at", "10 daphne_amazing"), ("lamp_pattern", "pulse"),
        ("cooldown", "20")]),
}


def shoot(repo, out_dir, kind, mfr):
    iso, ns, values = TITLES[mfr]
    scratch = tempfile.mkdtemp(prefix="pad1508-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": mfr,
                   "manufacturers": {mfr: {"extract_input": iso, "write_original": iso, "write_output": scratch}}}, f)
    proc, url = webui_shot.start_server(settings, scratch, extra_env={
        "PYTHONPATH": site.getusersitepackages(),
        "PYTHONUSERBASE": os.path.join(os.environ["APPDATA"], "Python")})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", mfr)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(2)
            time.sleep(2)
            st = webui_shot.state(url)["modes"][ns if ns == "jjp" else "spk"]
            first = st["modes"][0]["file"]
            webui_shot.api(url, "modes.%s_open" % ns, first)
            time.sleep(1.5)
            if kind == "after":
                for k, v in values:
                    webui_shot.api(url, "modes.%s_set" % ns, k, v)
                webui_shot.api(url, "modes.%s_check" % ns)
                time.sleep(1.5)
            groups = page.locator(".jjpm-group")
            n = groups.count()
            print(mfr, kind, "groups:", [groups.nth(i).locator(".jjpm-gt").inner_text() for i in range(n)])
            last = groups.nth(n - 1)
            last.scroll_into_view_if_needed()
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out_dir, "%s_%s_rules.png" % (kind, mfr)))
            browser.close()
    finally:
        proc.kill()


def main():
    repo, out_dir, kind = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    for mfr in ("jjp", "spooky"):
        shoot(repo, out_dir, kind, mfr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
