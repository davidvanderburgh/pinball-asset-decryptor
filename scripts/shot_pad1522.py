"""PAD-1522 proof shots: Compact with PAD on a card image's right-click menu,
its window, and a compact card's own icon.

    python scripts/shot_pad1522.py shell  <repo> <out.png> [--invoke <install>]
    python scripts/shot_pad1522.py window <out_dir>

``shell`` asks WINDOWS, not PAD: it registers the checkout's association
(webui/open_image.py association_values) for a scratch file type of its own
(``.padcard1522``, so the PC's real .raw setup is never touched), makes one
full-size and one compact card of that type, and draws what the shell answers
for each: the icon (IShellItemImageFactory, what a folder view draws) and the
right-click menu's entries (IContextMenu).  On main both cards have the one
icon and there is no Compact entry.  Everything it registered is removed.

``--invoke <install>`` then picks Compact with PAD on the full-size card
through that same menu, with <install> as the app folder (launcher.vbs, the
.pyw, python\\, pinball_decryptor\\): the real launch, no Administrator
prompt.  It waits for the window, checks the card came out compact with every
byte the same, shoots the window (<out>_window.png) and closes it.

``window`` shoots the window working down three cards and once it is done
(<out_dir>/after_compact_progress.png, after_compact_done.png and the two
stacked as after_compact_window.png), off screen.
"""
import ctypes
import hashlib
import os
import shutil
import sys
import tempfile
import time
import uuid
from ctypes import wintypes

EXT = ".padcard1522"
PROG = "PADTest1522.CardImage"
MB = 1024 * 1024


# ------------------------------------------------------------------ cards
def make_card(path, zeros_mb=96):
    with open(path, "wb") as f:
        f.write(os.urandom(3 * MB))
        f.write(bytes(zeros_mb * MB))
        f.write(os.urandom(2 * MB))
    return path


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(8 * MB), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ registry
def scratch_rows(oi, app_dir, icon_dll):
    """The checkout's own rows, moved onto the scratch type."""
    try:
        rows = oi.association_values(app_dir, icon_dll)
    except TypeError:                   # main before PAD-1522
        rows = oi.association_values(app_dir)
    out = {}
    for sub, name, data in rows:
        if sub.startswith(oi.PROGID):
            sub = PROG + sub[len(oi.PROGID):]
        elif sub.startswith(r"SystemFileAssociations\.raw" + "\\"):
            sub = "SystemFileAssociations\\" + EXT + sub[len(
                r"SystemFileAssociations\.raw"):]
        elif sub.startswith("CLSID\\"):
            pass
        else:
            continue
        out[(sub, name)] = data
    out[(EXT, "")] = PROG
    return out


def put_rows(rows):
    import winreg
    for (sub, name), data in rows.items():
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                "Software\\Classes\\" + sub, 0,
                                winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)
    notify()


def del_tree(path):
    import winreg
    hk = winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(hk, path, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as k:
            while True:
                try:
                    del_tree(path + "\\" + winreg.EnumKey(k, 0))
                except OSError:
                    break
        winreg.DeleteKey(hk, path)
    except OSError:
        pass


def remove_rows(rows):
    tops = set()
    for (sub, _name) in rows:
        parts = sub.split("\\")
        if parts[0] in ("CLSID", "SystemFileAssociations"):
            tops.add("\\".join(parts[:2]))
        else:
            tops.add(parts[0])
    for top in tops:
        del_tree("Software\\Classes\\" + top)
    notify()


def notify():
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


# ------------------------------------------------------------------ the shell
class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16),
                ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text):
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", ctypes.c_ushort),
                ("bmBitsPixel", ctypes.c_ushort),
                ("bmBits", ctypes.c_void_p)]


def shell_icon_image(path, px=96):
    """The picture the shell draws for *path* in a folder (icon only, never
    a thumbnail), as a PIL RGBA image."""
    from PIL import Image
    P = ctypes.c_void_p
    ole32, shell32, gdi32 = (ctypes.windll.ole32, ctypes.windll.shell32,
                             ctypes.windll.gdi32)
    ole32.CoInitialize(None)
    iid = GUID.of("{BCC18B79-BA16-442F-80C4-8A59C30C463B}")
    item = P()
    shell32.SHCreateItemFromParsingName.argtypes = [
        ctypes.c_wchar_p, P, ctypes.POINTER(GUID), ctypes.POINTER(P)]
    hr = shell32.SHCreateItemFromParsingName(path, None, ctypes.byref(iid),
                                             ctypes.byref(item))
    if hr:
        raise OSError("SHCreateItemFromParsingName 0x%08x" % (hr & 0xffffffff))
    vtbl = ctypes.cast(ctypes.cast(item, ctypes.POINTER(P))[0],
                       ctypes.POINTER(P))
    get_image = ctypes.WINFUNCTYPE(ctypes.c_long, P, SIZE, ctypes.c_int,
                                   ctypes.POINTER(P))(vtbl[3])
    hbm = P()
    hr = get_image(item, SIZE(px, px), 0x4, ctypes.byref(hbm))  # ICONONLY
    ctypes.WINFUNCTYPE(ctypes.c_ulong, P)(vtbl[2])(item)
    if hr:
        raise OSError("GetImage 0x%08x" % (hr & 0xffffffff))
    bm = BITMAP()
    gdi32.GetObjectW.argtypes = [P, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm))
    n = bm.bmWidthBytes * bm.bmHeight
    buf = ctypes.create_string_buffer(n)
    gdi32.GetBitmapBits.argtypes = [P, ctypes.c_long, ctypes.c_void_p]
    gdi32.GetBitmapBits(hbm, n, buf)
    gdi32.DeleteObject.argtypes = [P]
    gdi32.DeleteObject(hbm)
    im = Image.frombuffer("RGBA", (bm.bmWidth, bm.bmHeight), buf.raw, "raw",
                          "BGRA", bm.bmWidthBytes, 1)
    return im.copy()


def context_menu(path):
    """``(IContextMenu, hmenu, [(id, text)])`` for *path*: the classic
    right-click menu's entries as the shell builds them (None = a line)."""
    import pythoncom
    import win32con
    import win32gui
    from win32com.shell import shell
    pythoncom.CoInitialize()
    desktop = shell.SHGetDesktopFolder()
    folder_pidl = shell.SHParseDisplayName(os.path.dirname(path), 0)[0]
    parent = desktop.BindToObject(folder_pidl, None, shell.IID_IShellFolder)
    child = parent.ParseDisplayName(0, None, os.path.basename(path))[1]
    cm = parent.GetUIObjectOf(0, [child], shell.IID_IContextMenu, 0)[1]
    hmenu = win32gui.CreatePopupMenu()
    cm.QueryContextMenu(hmenu, 0, 1, 0x7FFF, 0)         # CMF_NORMAL
    user32 = ctypes.windll.user32
    items = []
    for i in range(win32gui.GetMenuItemCount(hmenu)):
        mid = user32.GetMenuItemID(hmenu, i)
        buf = ctypes.create_unicode_buffer(260)
        user32.GetMenuStringW(hmenu, i, buf, 260, win32con.MF_BYPOSITION)
        text = buf.value.replace("&", "")
        items.append((mid, text or None))
    return cm, hmenu, items


def invoke(cm, item_id):
    import win32con
    cm.InvokeCommand((0, 0, item_id - 1, None, None, win32con.SW_SHOWNORMAL,
                      0, None))


# ------------------------------------------------------------------ drawing
def _font(size, bold=False):
    from PIL import ImageFont
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    try:
        return ImageFont.truetype(os.path.join(
            os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), size)
    except OSError:
        return ImageFont.load_default()


def draw_sheet(out, cards, items):
    """*cards* ``[(label, sublabel, icon image)]``, *items* the menu."""
    from PIL import Image, ImageDraw
    W, H = 1100, 620
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((32, 22), "In a folder: the icon Windows draws for each card",
           font=_font(17, True), fill=(30, 30, 30))
    x = 60
    for label, sub, icon in cards:
        im.alpha_composite(icon, (x + 52, 80))
        w = d.textlength(label, font=_font(15))
        d.text((x + 100 - w / 2, 190), label, font=_font(15), fill=(20, 20, 20))
        w = d.textlength(sub, font=_font(13))
        d.text((x + 100 - w / 2, 214), sub, font=_font(13),
               fill=(110, 110, 110))
        small = icon.resize((16, 16), Image.LANCZOS)
        mid = icon.resize((32, 32), Image.LANCZOS)
        im.alpha_composite(mid, (x + 70, 256))
        im.alpha_composite(small, (x + 114, 264))
        x += 230
    d.text((32, 330), "List view size", font=_font(13), fill=(110, 110, 110))
    mx = 560
    d.line([(mx - 30, 20), (mx - 30, H - 20)], fill=(220, 220, 220), width=1)
    d.text((mx, 22), "Right-click the full-size card (classic menu)",
           font=_font(17, True), fill=(30, 30, 30))
    y = 66
    d.rounded_rectangle([mx, y - 8, mx + 420, H - 24], radius=8,
                        fill=(249, 249, 249), outline=(200, 200, 200))
    for _mid, text in items:
        if y > H - 60:
            d.text((mx + 18, y), "…", font=_font(15), fill=(60, 60, 60))
            break
        if text is None:
            d.line([(mx + 10, y + 5), (mx + 410, y + 5)], fill=(215, 215, 215))
            y += 11
            continue
        hot = "Compact with PAD" in text
        if hot:
            d.rounded_rectangle([mx + 6, y - 3, mx + 414, y + 25], radius=4,
                                fill=(221, 240, 228))
        d.text((mx + 18, y), text, font=_font(15, hot),
               fill=(15, 90, 45) if hot else (30, 30, 30))
        y += 28
    im.convert("RGB").save(out)


# ------------------------------------------------------------------ windows
def snap(hwnd, out):
    import win32gui
    import win32ui
    from PIL import Image
    left, top, right, bot = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bot - top
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
    bits = bmp.GetBitmapBits(True)
    im = Image.frombuffer("RGB", (w, h), bits, "raw", "BGRX", 0, 1)
    # the window rectangle includes the invisible resize border: keep what
    # is drawn (DWMWA_EXTENDED_FRAME_BOUNDS)
    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
        im = im.crop((r.left - left, r.top - top, r.right - left,
                      r.bottom - top))
    im.save(out)
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)


def find_window(title, timeout=30):
    import win32gui
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hwnd = win32gui.FindWindow(None, title)
        if hwnd and win32gui.IsWindowVisible(hwnd):
            return hwnd
        time.sleep(0.2)
    return 0


def elevated(pid):
    """Whether process *pid* runs elevated (None when it cannot be asked,
    which is itself what an elevated one answers a plain one)."""
    k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    tok = wintypes.HANDLE()
    try:
        if not adv.OpenProcessToken(wintypes.HANDLE(h), 0x8,
                                    ctypes.byref(tok)):
            return None
        val, n = wintypes.DWORD(), wintypes.DWORD()
        adv.GetTokenInformation(tok, 20, ctypes.byref(val), 4,
                                ctypes.byref(n))        # TokenElevation
        return bool(val.value)
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


# ------------------------------------------------------------------ modes
def shell_mode(repo, out, install=None):
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import sparse_card
    from pinball_decryptor.webui import open_image as oi
    work = tempfile.mkdtemp(prefix="pad1522-")
    full = make_card(os.path.join(work, "godzilla full size" + EXT))
    compact = make_card(os.path.join(work, "godzilla compact" + EXT))
    sparse_card.compact_file(compact)
    icon_dll = None
    try:
        from pinball_decryptor.webui import shell_icon
        icon_dll = shell_icon.stage(root=os.path.join(work, "stage"))
    except ImportError:                 # main: no handler
        pass
    rows = scratch_rows(oi, install or repo, icon_dll)
    put_rows(rows)
    try:
        time.sleep(1.0)
        cards = [("a full-size card", "takes its whole size on disk",
                  shell_icon_image(full)),
                 ("a compact card", "the same card, stored compact",
                  shell_icon_image(compact))]
        cm, _hmenu, items = context_menu(full)
        for _mid, text in items:
            print("menu:", text if text is not None else "-----")
        print("icons differ:", cards[0][2].tobytes() != cards[1][2].tobytes())
        draw_sheet(out, cards, items)
        print("wrote", out)
        if install:
            before = sha(full)
            mid = [m for m, t in items if t and "Compact with PAD" in t][0]
            invoke(cm, mid)
            hwnd = find_window("Compact card image")
            assert hwnd, "the compact window never came up"
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(pid))
            print("window pid %d elevated: %s" % (pid.value,
                                                  elevated(pid.value)))
            end = time.monotonic() + 60
            while time.monotonic() < end and not sparse_card.takes_less(full):
                time.sleep(0.2)
            time.sleep(1.0)
            print("compact after the click:", sparse_card.takes_less(full),
                  "| on disk %d of %d bytes" % (
                      sparse_card.on_disk_size(full), os.path.getsize(full)),
                  "| bytes unchanged:", sha(full) == before)
            snap(hwnd, os.path.splitext(out)[0] + "_window.png")
            shell_icon_image(full).save(
                os.path.splitext(out)[0] + "_icon_after_click.png")
            import win32con
            import win32gui
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(1.0)
            print("window closed:", not win32gui.IsWindow(hwnd))
    finally:
        remove_rows(rows)
        shutil.rmtree(work, ignore_errors=True)


def window_mode(out_dir):
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)
    from pinball_decryptor.core import sparse_card
    from pinball_decryptor.webui import compact_window as cw
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="pad1522-")
    names = ["godzilla_le-1_05_0.Release.16G.sdcard.raw",
             "jaws_le-1_01_0.Release.16G.sdcard.raw",
             "tmnt_le-1_55_0.Release.8G.sdcard.raw"]
    cards = [make_card(os.path.join(work, n), 64) for n in names]
    hold = {"on": False}

    def slowed(path, progress=None):
        """The real compact; the second card stops at 43% for the shot."""
        def step(done, total):
            progress(done, total)
            if path == cards[1] and done * 100 // total >= 43                     and not hold.get("was"):
                hold["on"] = hold["was"] = True
                while hold["on"]:
                    time.sleep(0.05)
        return sparse_card.compact_file(path, progress=step)

    import threading
    cw._dpi_aware()
    jobs = cw.Jobs(compact=slowed)
    done = threading.Event()

    def created(hwnd):
        # off screen: PrintWindow still draws it
        ctypes.windll.user32.SetWindowPos(
            ctypes.c_void_p(hwnd), None, -6000, 200, 0, 0, 0x1 | 0x4 | 0x10)

    def page(_hwnd, v):
        if not v["busy"]:
            done.set()

    win = cw.TaskWindow(jobs, poll_spool=False, on_created=created,
                        on_page=page)
    for c in cards:
        jobs.add(c)

    def shoot():
        while not hold["on"]:
            time.sleep(0.1)
        time.sleep(1.0)                 # a timer turn or two: it is drawn
        snap(win.hwnd, os.path.join(out_dir, "after_compact_progress.png"))
        hold["on"] = False
        done.wait(60)
        time.sleep(1.0)
        snap(win.hwnd, os.path.join(out_dir, "after_compact_done.png"))
        from PIL import Image
        a = Image.open(os.path.join(out_dir, "after_compact_progress.png"))
        b = Image.open(os.path.join(out_dir, "after_compact_done.png"))
        both = Image.new("RGB", (max(a.width, b.width),
                                 a.height + b.height + 24), (255, 255, 255))
        both.paste(a, (0, 0))
        both.paste(b, (0, a.height + 24))
        both.save(os.path.join(out_dir, "after_compact_window.png"))
        win.close()

    threading.Thread(target=shoot, daemon=True).start()
    assert win.run()
    shutil.rmtree(work, ignore_errors=True)
    print("wrote", out_dir)


def main():
    if sys.argv[1] == "shell":
        install = None
        if "--invoke" in sys.argv:
            install = os.path.abspath(sys.argv[sys.argv.index("--invoke") + 1])
        return shell_mode(os.path.abspath(sys.argv[2]),
                          os.path.abspath(sys.argv[3]), install)
    return window_mode(os.path.abspath(sys.argv[2]))


if __name__ == "__main__":
    main()
