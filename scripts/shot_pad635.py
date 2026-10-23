"""PAD-635 proof shots: the Audio tab says, for each sound, how many of the game code's sound
requests play it, and None for a sound the game never asks for.

    python scripts/shot_pad635.py <repo> <out_dir> <sound_requests.tsv> [--after]

Serves <repo> on a SCRATCH Godzilla Pro 1.16 project, as :mod:`shot_pad455` does: the audio of
a stock extract (``PAD455_AUDIO``, hard-linked) and the given ``sound_requests.tsv`` (one this
branch's Extract wrote: it carries the ``also`` column), the stock Pro 1.16 card as its source.
Writes, under the same names before and after:

- audio_requests.png   the list, the cursor on a played sound's Requests cell (its tip)
- audio_unused.png     sorted by Requests, fewest first: the None sounds on top, one's tip

With --old-extract (and the ``sound_requests.tsv`` an extract before v1.217.0 wrote, e.g.
PAD455_AUDIO's own) it writes only:

- audio_old_extract.png  a project extracted before the full map: no column, and the note
                         saying to extract again (PAD-635 round 2: a tester saw neither)

Needs Playwright (the user site-packages one) and the installed Edge.
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
import shot_pad312 as base  # noqa: E402
import shot_pad455 as p455  # noqa: E402

SCRATCH = os.environ.get("PAD635_SCRATCH", r"D:\Pinball\pad455_shots")
#: a played sound with a Sound Test name, and a sound no request plays
PLAYED = "idx0008"
UNUSED = "idx0014.wav"


def _project(scratch, tsv):
    dst = os.path.join(scratch, "gz116pro")
    aud = os.path.join(dst, "audio")
    os.makedirs(aud)
    sums = []
    for n in sorted(os.listdir(os.path.join(p455.AUDIO, "audio"))):
        os.link(os.path.join(p455.AUDIO, "audio", n), os.path.join(aud, n))
        sums.append("audio/%s\t%s" % (n, p455._md5(os.path.join(aud, n))))
    # an extracted project (the rail's lock and the change check read it)
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    shutil.copy2(tsv, os.path.join(dst, "sound_requests.tsv"))
    st = os.stat(p455.CARD)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": p455.CARD, "input_name": os.path.basename(p455.CARD),
                   "size": st.st_size, "mtime": int(st.st_mtime), "card_version": "1.16.0"}, f)
    return dst


def _hover(page, rel, after):
    """Put the cursor on *rel*'s Requests cell (after) or its Type cell (before: no column)."""
    row = page.locator(".aud-tbl .tr:has-text('%s')" % rel).first
    row.scroll_into_view_if_needed()
    cells = row.locator(".c")
    # play, Original Track, Length, Format, Type, [Requests], ...
    cell = cells.nth(5 if after else 4)
    target = cell.locator("span").first if after else cell
    target.hover()
    time.sleep(1.2)


def _shot(repo, out, tsv, after):
    os.makedirs(SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad635-", dir=SCRATCH)
    project = _project(scratch, tsv)
    proc, url = p455._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    pre = "after_" if after else "before_"
    print("repo:", repo, flush=True)
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
            st = state().get("audio") or {}
            print("req_cap:", st.get("req_cap"), "rows:", len(st.get("rows") or []), flush=True)
            if "--old-extract" in sys.argv:
                print("req_note:", st.get("req_note"), flush=True)
                page.mouse.move(5, 990)
                time.sleep(0.6)
                page.screenshot(path=os.path.join(out, pre + "audio_old_extract.png"))
                print("page errors:", errors, flush=True)
                browser.close()
                return
            played = next((r for r in st.get("rows") or [] if PLAYED in r["k"]), {})
            print("played row:", played.get("k"), played.get("rq"), played.get("rq_tip"))
            _hover(page, PLAYED, after)
            page.screenshot(path=os.path.join(out, pre + "audio_requests.png"))
            # fewest first: the sort's first click is most first, the second fewest
            api("audio.sort", "rq")
            api("audio.sort", "rq")
            time.sleep(2)
            st = state().get("audio") or {}
            rows = st.get("rows") or []
            print("sort:", st.get("sort"), "first rows:", [(r["k"], r.get("rq")) for r in rows[:4]])
            print("None rows:", sum(1 for r in rows if r.get("rq") == 0), flush=True)
            page.locator(".aud-tblwrap .vt, .aud-tblwrap [class*=scroll]").first.evaluate(
                "el => el.scrollTop = 0") if after else None
            _hover(page, UNUSED, after)
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
    repo, out, tsv = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    _shot(repo, out, tsv, "--after" in sys.argv)


if __name__ == "__main__":
    main()
