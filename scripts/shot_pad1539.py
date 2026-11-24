"""PAD-1539 proof shots: Copy with PAD keeps a compact card compact.

    python scripts/shot_pad1539.py menu <repo> <out.png>
    python scripts/shot_pad1539.py copy <repo> <out.png> explorer|pad|zip [DEST]

``menu`` draws the classic right-click menu Windows builds for a compact
card of a scratch type registered with <repo>'s rows (shot_pad1522's, never
the PC's real .raw setup); main has no Copy entry.

``copy`` makes a compact 4 GB card on C:\\tmp, copies it to DEST
(``D:\\tmp_PAD-1539``) with Explorer's own engine (``explorer``,
Shell.Application CopyHere, what Copy/Paste or a drag to another drive does)
or with Copy with PAD (``pad``: the Copy window, off screen), prints how
long it took and what it takes on disk there, and shoots Windows' own
Properties of the copy (its "Size on disk"); for ``pad`` the Copy window's
done page beside it.  ``zip`` is ``pad`` with DEST standing in for a
Google Drive folder (nothing is written to the real Drive): the card goes in
as a .zip, as it does wherever a compact card cannot be kept.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1522 as s22                                  # noqa: E402
import shot_pad1535 as s35                                  # noqa: E402

NAME = s35.NAME


def draw_menu(out, items):
    from PIL import Image, ImageDraw
    rows = [t for _m, t in items]
    W = 520
    H = 70 + sum(11 if t is None else 28 for t in rows) + 24
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((20, 18), "Right-click a compact card (classic menu)",
           font=s22._font(17, True), fill=(30, 30, 30))
    y = 62
    d.rounded_rectangle([14, y - 8, W - 14, H - 12], radius=8,
                        fill=(249, 249, 249), outline=(200, 200, 200))
    for t in rows:
        if t is None:
            d.line([(24, y + 5), (W - 24, y + 5)], fill=(215, 215, 215))
            y += 11
            continue
        hot = "Copy with PAD" in t
        if hot:
            d.rounded_rectangle([20, y - 3, W - 20, y + 25], radius=4,
                                fill=(221, 240, 228))
        d.text((32, y), t, font=s22._font(15, hot),
               fill=(15, 90, 45) if hot else (30, 30, 30))
        y += 28
    im.save(out)


def menu_mode(repo, out):
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import sparse_card
    from pinball_decryptor.webui import open_image as oi
    work = tempfile.mkdtemp(prefix="pad1539-")
    card = s22.make_card(os.path.join(work, "godzilla compact" + s22.EXT))
    sparse_card.compact_file(card)
    rows = s22.scratch_rows(oi, repo, None)
    s22.put_rows(rows)
    try:
        time.sleep(1.0)
        _cm, _h, items = s22.context_menu(card)
        for _m, t in items:
            print("menu:", t if t is not None else "-----")
        draw_menu(out, items)
    finally:
        s22.remove_rows(rows)
        shutil.rmtree(work, ignore_errors=True)
    print("wrote", out)


def copy_mode(repo, out, how, dest):
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import sparse_card
    os.makedirs(dest, exist_ok=True)
    work = r"C:\tmp\PAD-1539\shot"
    os.makedirs(work, exist_ok=True)
    for p in (os.path.join(work, NAME), os.path.join(dest, NAME)):
        if os.path.exists(p):
            os.remove(p)
    src = s35.make_compact(os.path.join(work, NAME), sparse_card)
    print("on C: %d of %d bytes on disk" % (sparse_card.on_disk_size(src),
                                            os.path.getsize(src)))
    dst = os.path.join(dest, NAME)
    window_png = None
    t = time.monotonic()
    if how == "explorer":
        ps = ("$s=New-Object -ComObject Shell.Application; "
              "$s.Namespace('%s').CopyHere('%s', 0x614)" % (dest, src))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True)
        size = os.path.getsize(src)
        while not (os.path.exists(dst) and os.path.getsize(dst) == size):
            time.sleep(0.1)
        took = time.monotonic() - t
        time.sleep(2.0)
    else:
        from pinball_decryptor.webui import compact_window as cw
        cw._dpi_aware()
        if how == "zip":
            dst += ".zip"
            if os.path.exists(dst):
                os.remove(dst)
            jobs = cw.CopyJobs(dest, move=lambda *a, **k: (
                sparse_card.copy_card(*a, zipped="Google Drive", **k)))
        else:
            jobs = cw.CopyJobs(dest)
        done = threading.Event()
        took = [0.0]

        def created(hwnd):
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(hwnd), None, -6000, 200, 0, 0, 0x1 | 0x4
                | 0x10)

        def page(_h, v):
            if not v["busy"]:
                took[0] = time.monotonic() - t
                done.set()

        win = cw.TaskWindow(jobs, poll_spool=False, on_created=created,
                            on_page=page)
        jobs.add(src)
        window_png = os.path.splitext(out)[0] + "_window.png"

        def shoot():
            done.wait(300)
            time.sleep(1.0)
            s22.snap(win.hwnd, window_png)
            win.close()

        threading.Thread(target=shoot, daemon=True).start()
        assert win.run()
        took = took[0]
    print("%s copy took %.1f s; on %s: %d of %d bytes on disk; original "
          "still there: %s" % (how, took, dest[:2],
                               sparse_card.on_disk_size(dst),
                               os.path.getsize(src), os.path.exists(src)))
    if how == "zip":
        import hashlib
        import zipfile

        def sha(f):
            h = hashlib.sha256()
            for b in iter(lambda: f.read(1 << 24), b""):
                h.update(b)
            return h.hexdigest()
        with zipfile.ZipFile(dst) as z, z.open(NAME) as zf, \
                open(src, "rb") as sf:
            print("zip holds the same card:", sha(zf) == sha(sf))
    elif how == "pad":
        import filecmp
        print("same bytes:", filecmp.cmp(src, dst, shallow=False))
    props = os.path.splitext(out)[0] + "_props.png"
    s35.properties(dst, props)
    from PIL import Image
    parts = [Image.open(p) for p in (window_png, props) if p]
    sheet = Image.new("RGB", (sum(p.width for p in parts) + 24 * (
        len(parts) - 1), max(p.height for p in parts)), (255, 255, 255))
    x = 0
    for p in parts:
        sheet.paste(p, (x, 0))
        x += p.width + 24
    sheet.save(out)
    os.remove(dst)
    os.remove(src)
    print("wrote", out)


def main():
    if sys.argv[1] == "menu":
        return menu_mode(os.path.abspath(sys.argv[2]),
                         os.path.abspath(sys.argv[3]))
    return copy_mode(os.path.abspath(sys.argv[2]),
                     os.path.abspath(sys.argv[3]), sys.argv[4],
                     sys.argv[5] if len(sys.argv) > 5 else r"D:\tmp_PAD-1539")


if __name__ == "__main__":
    main()
