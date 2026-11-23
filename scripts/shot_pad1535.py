"""PAD-1535 proof shots: Move with PAD keeps a compact card compact.

    python scripts/shot_pad1535.py menu <repo> <out.png>
    python scripts/shot_pad1535.py move <repo> <out.png> explorer|pad [DEST]

``menu`` registers <repo>'s association for a scratch type (shot_pad1522's
rows, never the PC's real .raw setup), and draws the classic right-click
menu Windows builds for a compact card of it.  Main has no Move entry.

``move`` makes a compact 4 GB card on C:\\tmp, moves it to DEST
(``D:\\tmp_PAD-1535``) with Explorer's own engine (``explorer``,
Shell.Application MoveHere, what a drag or Cut/Paste does) or with Move with
PAD (``pad``: the Move window, off screen), prints how long it took and what
it takes on disk there, and shoots Windows' own Properties of the moved card
(its "Size on disk"); for ``pad`` the Move window's done page beside it.
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

MB = 1024 * 1024
NAME = "godzilla_le-1_05_0.Release.16G.sdcard.raw"


def make_compact(path, sparse_card, size=4 << 30):
    with open(path, "wb") as f:
        f.truncate(size)
        for off in (0, 900 * MB, 2600 * MB):
            f.seek(off)
            f.write(os.urandom(60 * MB))
    sparse_card.compact_file(path)
    return path


def menu_mode(repo, out):
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import sparse_card
    from pinball_decryptor.webui import open_image as oi
    work = tempfile.mkdtemp(prefix="pad1535-")
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
        hot = "Move with PAD" in t
        if hot:
            d.rounded_rectangle([20, y - 3, W - 20, y + 25], radius=4,
                                fill=(221, 240, 228))
        d.text((32, y), t, font=s22._font(15, hot),
               fill=(15, 90, 45) if hot else (30, 30, 30))
        y += 28
    im.save(out)


def properties(path, out):
    """Shoot Windows' Properties of *path*, off screen."""
    import win32con
    import win32gui
    from win32com.shell import shell, shellcon
    shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_INVOKEIDLIST,
                         lpVerb="properties", lpFile=path,
                         nShow=win32con.SW_SHOWNORMAL)
    import win32process
    hwnd, end = 0, time.monotonic() + 30
    while not hwnd and time.monotonic() < end:
        found = []

        def each(h, _):
            if win32process.GetWindowThreadProcessId(h)[1] == os.getpid()                     and win32gui.IsWindowVisible(h)                     and win32gui.GetWindowText(h).endswith(" Properties"):
                found.append(h)
        win32gui.EnumWindows(each, None)
        hwnd = found[0] if found else 0
        time.sleep(0.2)
    assert hwnd, "no Properties window"
    ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), None, -6000,
                                      200, 0, 0, 0x1 | 0x4 | 0x10)
    time.sleep(3.0)                     # Size on disk is filled in late
    s22.snap(hwnd, out)
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    time.sleep(0.5)


def move_mode(repo, out, how, dest):
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import sparse_card
    os.makedirs(dest, exist_ok=True)
    work = r"C:\tmp\PAD-1535\shot"
    os.makedirs(work, exist_ok=True)
    for p in (os.path.join(work, NAME), os.path.join(dest, NAME)):
        if os.path.exists(p):
            os.remove(p)
    src = make_compact(os.path.join(work, NAME), sparse_card)
    print("on C: %d of %d bytes on disk" % (sparse_card.on_disk_size(src),
                                            os.path.getsize(src)))
    dst = os.path.join(dest, NAME)
    window_png = None
    t = time.monotonic()
    if how == "explorer":
        ps = ("$s=New-Object -ComObject Shell.Application; "
              "$s.Namespace('%s').MoveHere('%s', 0x614)" % (dest, src))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True)
        while os.path.exists(src):
            time.sleep(0.1)
        took = time.monotonic() - t
    else:
        from pinball_decryptor.webui import compact_window as cw
        cw._dpi_aware()
        jobs = cw.MoveJobs(dest)
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
    print("%s move took %.1f s; on %s: %d of %d bytes on disk" % (
        how, took, dest[:2], sparse_card.on_disk_size(dst),
        os.path.getsize(dst)))
    props = os.path.splitext(out)[0] + "_props.png"
    properties(dst, props)
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
    print("wrote", out)


def main():
    if sys.argv[1] == "menu":
        return menu_mode(os.path.abspath(sys.argv[2]),
                         os.path.abspath(sys.argv[3]))
    return move_mode(os.path.abspath(sys.argv[2]),
                     os.path.abspath(sys.argv[3]), sys.argv[4],
                     sys.argv[5] if len(sys.argv) > 5 else r"D:\tmp_PAD-1535")


if __name__ == "__main__":
    main()
