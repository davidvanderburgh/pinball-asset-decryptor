"""PAD-636 proof shots: on Led Zeppelin Pro 1.22 the Audio tab's Sound Test names and Requests
column read each descriptor only as far as the next one starts, and whatever its marker's
parameter byte.

    python scripts/shot_pad636.py <repo> <out_dir> <extracted project> [--after]

Serves <repo> on a SCRATCH copy of an audio-only Led Zeppelin Pro 1.22 extract (main's
Extract's for the before shots, this branch's for the after ones), the stock card as its
source. Writes, under the same names before and after:

- audio_names.png      searched for "WORLD TOUR": the Sound Test names each record gets
- audio_unused.png     idx010x sorted by Requests, fewest first: the None sounds on top

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("PAD455_CARD", r"D:\Pinball\images\Stern\spike2"
                      r"\led_zeppelin_pro-1_22_0.Release.8G.sdcard.raw")
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad455 as p455  # noqa: E402

SCRATCH = os.environ.get("PAD636_SCRATCH", r"C:\tmp\PAD-636\shots")
NAMED = "idx0087"
UNUSED = "idx0100"


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _project(scratch, src):
    dst = os.path.join(scratch, "lzpro122")
    aud = os.path.join(dst, "audio")
    os.makedirs(aud)
    sums = []
    for n in sorted(os.listdir(os.path.join(src, "audio"))):
        os.link(os.path.join(src, "audio", n), os.path.join(aud, n))
        sums.append("audio/%s\t%s" % (n, _md5(os.path.join(aud, n))))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    for n in ("sound_requests.tsv", "sound_test_names.csv"):
        shutil.copy2(os.path.join(src, n), os.path.join(dst, n))
    st = os.stat(p455.CARD)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": p455.CARD, "input_name": os.path.basename(p455.CARD),
                   "size": st.st_size, "mtime": int(st.st_mtime), "card_version": "1.22.0"}, f)
    return dst


def _search(page, text):
    """Type *text* into the Audio tab's search box."""
    box = page.locator(".search input").first
    box.fill(text)
    box.press("Enter")
    time.sleep(2)


def _hover(page, rel):
    """The cursor on *rel*'s Requests cell (its tip)."""
    row = page.locator(".aud-tbl .tr:has-text('%s')" % rel).first
    row.scroll_into_view_if_needed()
    row.locator(".c").nth(5).locator("span").first.hover()
    time.sleep(1.2)


def _shot(repo, out, src, after):
    os.makedirs(SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad636-", dir=SCRATCH)
    project = _project(scratch, src)
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
            for k in ("idx0057", NAMED, "idx0278", "idx0517", "idx0519", UNUSED):
                r = next((r for r in rows if k in r["k"]), {})
                print("row:", r.get("k"), r.get("rq"), r.get("rq_tip"), flush=True)
            _search(page, "WORLD TOUR")
            _hover(page, NAMED)
            page.screenshot(path=os.path.join(out, pre + "audio_names.png"))
            api("audio.sort", "rq")
            api("audio.sort", "rq")
            time.sleep(2)
            rows = (state().get("audio") or {}).get("rows") or []
            print("None rows:", sum(1 for r in rows if r.get("rq") == 0), flush=True)
            _search(page, "idx010")
            _hover(page, UNUSED)
            page.screenshot(path=os.path.join(out, pre + "audio_unused.png"))
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
