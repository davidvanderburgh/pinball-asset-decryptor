"""PAD-637 proof shots: Led Zeppelin Pro 1.22's multi-band records (twelve or twenty-four variants of one
sound) extract as their variants one after another instead of stationary noise.

    python scripts/shot_pad637.py <repo> <out_dir> <extracted project> [--after]

Serves <repo> on a SCRATCH copy of an audio-only Led Zeppelin Pro 1.22 extract (main's Extract's for the
before shots, this branch's for the after ones), the stock card as its source. Writes, under the same names
before and after:

- audio_variants.png   idx003x listed, idx0031 (twelve variants) picked: its length, its spectrogram and
                       the Format cell's tip
- audio_seq.png        searched for "SEQ", idx0057 SE FX SEQ EM FRENZY AWARD (twenty-four) picked

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("PAD455_CARD", r"D:\Pinball\images\Stern\spike2"
                      r"\led_zeppelin_pro-1_22_0.Release.8G.sdcard.raw")
os.environ.setdefault("PAD636_SCRATCH", r"C:\tmp\PAD-637\shots")
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad455 as p455  # noqa: E402
import shot_pad636 as p636  # noqa: E402


def _pick(page, rel):
    """Click *rel*'s row so the Original panel shows it."""
    row = page.locator(".aud-tbl .tr:has-text('%s')" % rel).first
    row.scroll_into_view_if_needed()
    row.locator(".c").nth(1).click()
    time.sleep(3)


def _hover_fmt(page, rel):
    """The cursor on *rel*'s Format cell (its variants tip, after)."""
    row = page.locator(".aud-tbl .tr:has-text('%s')" % rel).first
    row.locator(".c").nth(3).locator("span").first.hover()
    time.sleep(1.2)


def _shot(repo, out, src, after):
    os.makedirs(p636.SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad637-", dir=p636.SCRATCH)
    project = p636._project(scratch, src)
    if os.path.exists(os.path.join(src, "sound_variants.json")):
        shutil.copy2(os.path.join(src, "sound_variants.json"), project)
    proc, url = p455._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    pre = "after_" if after else "before_"
    print("repo:", repo, "project:", src, flush=True)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            base._wait_scan(state, "audio")
            deadline = time.time() + 300
            while time.time() < deadline and "still checking" in (
                    (state().get("audio") or {}).get("status") or ""):
                time.sleep(1)
            time.sleep(2)
            rows = (state().get("audio") or {}).get("rows") or []
            for k in ("idx0031", "idx0057", "idx0390"):
                r = next((r for r in rows if k in r["k"]), {})
                print("row:", {x: r.get(x) for x in ("k", "len", "fmt", "type", "fmt_tip")}, flush=True)
            p636._search(page, "idx003")
            _pick(page, "idx0031")
            _hover_fmt(page, "idx0031")
            page.screenshot(path=os.path.join(out, pre + "audio_variants.png"))
            p636._search(page, "SEQ")
            _pick(page, "idx0057")
            page.screenshot(path=os.path.join(out, pre + "audio_seq.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    repo, out, src = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    _shot(repo, out, src, "--after" in sys.argv)


if __name__ == "__main__":
    main()
