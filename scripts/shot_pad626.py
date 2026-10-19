"""PAD-626 proof: how long Select card's "Card details" tile takes to fill.

    python scripts/shot_pad626.py <repo> <out_dir> [<prefix>]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for
the "before" shots).  The card file is first dropped from the Windows file cache (a
non-buffered open purges it), so every read is the cold one David gets after a reboot
or after using other cards.  Then:

1. The app starts on a scratch project, Select card open, and the Godzilla LE 1.16
   card is picked.  ``<prefix>select_card.png`` is the page 6 s later; the times to
   the first rows and to the whole report are printed.
2. The app is closed, the card dropped from the cache again, and the app opened
   again on the same card (what David sees each time he starts it).
   ``<prefix>select_card_reopen.png`` is the page 1.5 s after it is picked.

Set PAD626_CARD to another card image to point it at it.
"""

import ctypes
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

CARD = os.environ.get("PAD626_CARD") or (
    r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")


def purge(path):
    """Drop *path* from the Windows file cache: the cache manager purges a
    file's cached pages on a non-buffered open when nothing else holds them."""
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                              wintypes.HANDLE]
    h = k.CreateFileW(path, 0x80000000, 7, None, 3, 0x20000000, None)
    if h and h != wintypes.HANDLE(-1).value:
        k.CloseHandle(h)


def _text(page):
    loc = page.locator(".c-info")
    return (loc.inner_text() or "") if loc.count() else ""


def _pick_and_time(url, page, shot, at):
    """Pick the card; screenshot *shot* *at* s later; return the seconds to
    the first rows and to the whole report."""
    t0 = time.time()
    webui_shot.api(url, "extract.use_recent", "input", CARD)
    first = full = None
    shot_done = False
    while time.time() - t0 < 600:
        txt = _text(page)
        now = time.time() - t0
        if first is None and "Firmware" in txt:
            first = now
        if (full is None and "Firmware" in txt
                and "Counting the videos" not in txt):
            full = now
        if not shot_done and now >= at:
            page.screenshot(path=shot)
            shot_done = True
        if full is not None and shot_done:
            break
        time.sleep(0.05)
    return first, full


def _session(repo, scratch, project, shot, at):
    proc, url = S._serve(repo, scratch, project)
    try:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1500})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "card")
            time.sleep(1)
            got = _pick_and_time(url, page, shot, at)
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
            return got
    finally:
        proc.terminate()
        time.sleep(2)


def _fmt(x):
    return "never" if x is None else "%.1f s" % x


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3] if len(sys.argv) > 3 else ""
    os.makedirs(out_dir, exist_ok=True)
    # a report a previous run kept for this card is not this run's to find
    sys.path.insert(0, repo)
    from pinball_decryptor.webui import card_preview as CP
    ck = CP.card_key(CARD)
    if ck:
        try:
            os.remove(os.path.join(CP.cache_root(), ck, "info.json"))
        except OSError:
            pass
    scratch = tempfile.mkdtemp(prefix="pad626-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    purge(CARD)
    first, full = _session(repo, scratch, project,
                           os.path.join(out_dir, prefix + "select_card.png"), 6.0)
    print("first look: rows after %s, whole report after %s"
          % (_fmt(first), _fmt(full)), flush=True)
    purge(CARD)
    first, full = _session(repo, scratch, project,
                           os.path.join(out_dir, prefix + "select_card_reopen.png"),
                           1.5)
    print("app opened again: rows after %s, whole report after %s"
          % (_fmt(first), _fmt(full)), flush=True)


if __name__ == "__main__":
    main()
