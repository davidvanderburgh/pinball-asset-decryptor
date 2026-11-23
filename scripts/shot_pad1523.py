"""PAD-1523 proof shot: the Windows 11 SHORT right-click menu on a card.

    python scripts/shot_pad1523.py <card image> <out.png> [--classic]

Opens Explorer on the card's folder with the card selected, right-clicks
it with the mouse (found through UI Automation; with --classic it is a
Shift+right-click, which opens the classic menu), photographs the
screen, crops it to the menu and the Explorer window behind it, then
closes both.  Unlike scripts/shot_pad1522.py, which built the classic menu
through IContextMenu and so never showed what Windows 11 lists first,
this is the menu a user sees.  Prints every line of window text the menu
offers to UI Automation as well, so the shot comes with a readable list.
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.windll.user32
VK_SHIFT, VK_ESCAPE = 0x10, 0x1B
KEYUP = 2


def _windows():
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h):
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cls, 256)
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, title, 256)
            r = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            out.append((h, cls.value, title.value,
                        (r.left, r.top, r.right, r.bottom)))
        return True
    user32.EnumWindows(cb, 0)
    return out


def _key(vk, up=False):
    user32.keybd_event(vk, 0, KEYUP if up else 0, 0)


def _front(h):
    # Windows refuses SetForegroundWindow to a process that is not the
    # foreground one; joining the foreground window's input lifts that
    # (a tap of Alt would too, but it moves Explorer's focus to its toolbar)
    fg = user32.GetForegroundWindow()
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    them = user32.GetWindowThreadProcessId(fg, None)
    user32.AttachThreadInput(me, them, True)
    user32.ShowWindow(h, 9)
    user32.BringWindowToTop(h)
    user32.SetForegroundWindow(h)
    user32.AttachThreadInput(me, them, False)


UIA_PS = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$w = [Windows.Automation.AutomationElement]::FromHandle([IntPtr]%d)
$c = New-Object Windows.Automation.PropertyCondition(
  [Windows.Automation.AutomationElement]::NameProperty, '%s')
$e = $w.FindFirst([Windows.Automation.TreeScope]::Descendants, $c)
$r = $e.Current.BoundingRectangle
"$($r.Left) $($r.Top) $($r.Width) $($r.Height)"
"""


UIA_ROOT_PS = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$c = New-Object Windows.Automation.PropertyCondition(
  [Windows.Automation.AutomationElement]::NameProperty, '%s')
$e = [Windows.Automation.AutomationElement]::RootElement.FindFirst(
  [Windows.Automation.TreeScope]::Descendants, $c)
$r = $e.Current.BoundingRectangle
"$($r.Left) $($r.Top) $($r.Width) $($r.Height)"
"""


def _menu_point(label):
    """Screen point of the open menu's entry *label*, or None"""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          UIA_ROOT_PS % label.replace("'", "''")],
                         capture_output=True, text=True).stdout.split()
    try:
        left, top, w, ht = (float(v) for v in out[:4])
    except ValueError:
        return None
    return (int(left + w / 2), int(top + ht / 2)) if w > 0 else None


def _item_point(h, name):
    """Screen point inside the card's name in Explorer's list."""
    stem = os.path.splitext(name)[0]        # the list hides .raw
    for label in (name, stem):
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             UIA_PS % (h, label.replace("'", "''"))],
            capture_output=True, text=True).stdout.split()
        try:
            left, top, w, ht = (float(v) for v in out[:4])
        except ValueError:
            continue
        if w > 0:
            return int(left + min(w / 2, 120)), int(top + ht / 2)
    sys.exit("card %r not found in the Explorer list" % name)


def main(argv):
    card, out = os.path.abspath(argv[1]), argv[2]
    classic = "--classic" in argv
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    before = {w[0] for w in _windows()}
    # verbatim: a quoted "/select,<path>" with brackets in it opens Documents
    subprocess.Popen('explorer.exe /select,"%s"' % card)
    win = None
    for _ in range(60):
        time.sleep(0.25)
        new = [w for w in _windows() if w[0] not in before
               and w[1] == "CabinetWClass"]
        if new:
            win = new[0]
            break
    if not win:
        sys.exit("no Explorer window came up")
    h = win[0]
    # a fixed size and place, so a before and an after shot pair up
    user32.MoveWindow(h, 80, 80, 1100, 700, True)
    time.sleep(2.5)                   # the folder lists and selects the card
    _front(h)
    time.sleep(0.8)
    shown = {w[0] for w in _windows()}
    x, y = _item_point(h, os.path.basename(card))
    user32.SetCursorPos(x, y)
    time.sleep(0.3)
    if classic:
        _key(VK_SHIFT)
    user32.mouse_event(0x0008, 0, 0, 0, 0)        # right button down
    user32.mouse_event(0x0010, 0, 0, 0, 0)        # and up
    if classic:
        _key(VK_SHIFT, True)
    user32.SetCursorPos(x + 600, y + 400)         # off the menu, unhovered
    time.sleep(2.5)                   # the short menu fades in
    if "--hover" in argv:             # open an entry's flyout, to see in it
        what = argv[argv.index("--hover") + 1]
        pt = (tuple(int(v) for v in what.split(",")) if what[:1].isdigit()
              else _menu_point(what))
        print("hover", pt)
        if pt:
            user32.SetCursorPos(pt[0] - 40, pt[1])
            for _ in range(8):        # a real move: a jump alone hovers nothing
                user32.mouse_event(0x0001, 5, 0, 0, 0)
                time.sleep(0.05)
            time.sleep(2.0)
            if "--click" in argv:      # and choose it, as a user would
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(3.0)
    menus = [w for w in _windows() if w[0] not in shown]
    for m in menus:
        print("menu window:", m[1], m[3])
    from PIL import ImageGrab
    shot = ImageGrab.grab(all_screens=True)
    r = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    box = [r.left, r.top, r.right, r.bottom]
    for m in menus:
        box = [min(box[0], m[3][0]), min(box[1], m[3][1]),
               max(box[2], m[3][2]), max(box[3], m[3][3])]
    # ImageGrab's origin is the virtual screen's top left
    vx = user32.GetSystemMetrics(76)
    vy = user32.GetSystemMetrics(77)
    crop = shot.crop((box[0] - vx, box[1] - vy, box[2] - vx, box[3] - vy))
    crop.save(out)
    print("wrote", out, crop.size)
    _key(VK_ESCAPE)
    _key(VK_ESCAPE, True)
    time.sleep(0.3)
    _key(VK_ESCAPE)
    _key(VK_ESCAPE, True)
    user32.PostMessageW(h, 0x0010, 0, 0)          # WM_CLOSE


if __name__ == "__main__":
    main(sys.argv)
