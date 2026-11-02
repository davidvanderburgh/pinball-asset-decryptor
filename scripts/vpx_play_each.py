"""Play every (PAD) table in the tables folder in the real Visual Pinball,
one after another, and say which loaded and served its balls (PAD-943,
David: "make sure you try and run each and every game in the list to ensure
it can load and at least play one or two balls").

    python scripts/vpx_play_each.py [--only word,...] [--balls 2] [--this-kit]
        [--out report.json] [--wait-attach 150] [--wait-ball 150] [--list]

Each table is opened as the tab's Play opens it (VPinballX64.exe -play), the
game behind it starts through PAD.Controller, and the run is judged from the
desktop and the controller's log: no error dialog from Visual Pinball (a
script error, the patch's "Can't load / Can't start"), the controller
attached to the game, a coin and Start began a game, the trough served a
ball (solenoid 1), the ball was plunged and, once it drained, a second ball
was served. Then the player window is closed (so the controller stops the
run it started) and the next table begins. The report is a table on stdout
and --out as JSON; the exit code is the number of tables that failed.

--this-kit registers THIS checkout's PAD.Controller for the current user
(HKCU\\Software\\Classes, no elevation) for the run and removes that again
at the end: the machine-wide registration (an installed app's, or another
checkout's) is untouched. A Spike 1 table needs this until the kit with
Spike 1 in it is the registered one.

It takes the desktop: Visual Pinball's windows open and close in turn, about
three minutes a table, and the keys it presses go to the player window.
Never run it while someone is playing; it refuses to start while Visual
Pinball is open.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu", "vpx")
sys.path.insert(0, KIT)

import padcontroller  # noqa: E402
import padvpx  # noqa: E402
import vpxsetup  # noqa: E402

VK = {"5": 0x35, "1": 0x31, "enter": 0x0D}
KEYEVENTF_KEYUP = 0x0002
WM_CLOSE = 0x0010
u32 = ctypes.windll.user32


def windows():
    """[(hwnd, title, class, pid)] of every visible top-level window."""
    out = []

    def cb(h, _l):
        if not u32.IsWindowVisible(h):
            return True
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(h, buf, 256)
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, cls, 64)
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        out.append((h, buf.value, cls.value, pid.value))
        return True
    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return out


def dialog_text(hwnd):
    """The static texts of a dialog (its message)."""
    parts = []

    def cb(h, _l):
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, cls, 64)
        n = u32.GetWindowTextLengthW(h)
        if cls.value in ("Static", "Edit", "RichEdit20W", "RichEdit20A") and n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            parts.append(buf.value.strip())
        return True
    u32.EnumChildWindows(ctypes.c_void_p(hwnd), ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return " | ".join(p for p in parts if p)


def vpx_pids():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq VPinballX64.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:                                       # noqa: BLE001
        return []
    pids = []
    for line in out.splitlines():
        cells = [c.strip('"') for c in line.split('","')]
        if len(cells) > 1 and cells[0].lower() == "vpinballx64.exe":
            try:
                pids.append(int(cells[1]))
            except ValueError:
                pass
    return pids


def error_dialogs(pids):
    """[(title, text)] of the dialogs Visual Pinball has up: a script error,
    a MsgBox from the patch ("Can't start the game"), a VPX error."""
    out = []
    for h, title, cls, pid in windows():
        if pid in pids and cls == "#32770":
            out.append((title, dialog_text(h)))
    return out


def player_window(pids):
    for h, title, cls, pid in windows():
        if pid in pids and title == "Visual Pinball Player":
            return h
    return None


def press(key, hold=0.08):
    vk = VK[key]
    u32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def focus(hwnd):
    u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    time.sleep(0.3)


def log_tail(path, start):
    try:
        with open(path, "rb") as f:
            f.seek(start)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def log_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def sol_pulses(text, number=1):
    """How many times solenoid `number` went on (the trough's up-kicker)."""
    return sum(1 for line in text.splitlines() if line.rstrip().endswith("sol %d -> 1" % number))


# ----------------------------------------------------------- this kit's COM --
CLSID = padcontroller.PadController._reg_clsid_
USER_CLASSES = r"Software\Classes"


def register_this_kit():
    """PAD.Controller for the current user -> this checkout's padcontroller,
    with the LocalServer32 the machine-wide registration uses. HKCU wins over
    HKLM in HKCR, and needs no elevation."""
    import winreg
    try:
        server = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, r"CLSID\%s\LocalServer32" % CLSID)
    except OSError:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        import win32com.server
        local = os.path.join(os.path.dirname(win32com.server.__file__), "localserver.py")
        server = '%s "%s" %s' % (pyw, local, CLSID)
    root = winreg.HKEY_CURRENT_USER
    base = USER_CLASSES + r"\CLSID\%s" % CLSID
    winreg.SetValue(root, base, winreg.REG_SZ, "PAD controller for Visual Pinball (this checkout, per user)")
    winreg.SetValue(root, base + r"\LocalServer32", winreg.REG_SZ, server)
    winreg.SetValue(root, base + r"\ProgID", winreg.REG_SZ, "PAD.Controller")
    winreg.SetValue(root, base + r"\PythonCOM", winreg.REG_SZ, "padcontroller.PadController")
    winreg.SetValue(root, base + r"\PythonCOMPath", winreg.REG_SZ, KIT)
    winreg.SetValue(root, USER_CLASSES + r"\PAD.Controller", winreg.REG_SZ, "PAD controller for Visual Pinball")
    winreg.SetValue(root, USER_CLASSES + r"\PAD.Controller\CLSID", winreg.REG_SZ, CLSID)
    print("PAD.Controller for this user -> %s (until this run ends)" % KIT, flush=True)


def unregister_this_kit():
    import winreg

    def rm(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                subs = []
                i = 0
                while True:
                    try:
                        subs.append(winreg.EnumKey(k, i))
                        i += 1
                    except OSError:
                        break
            for s in subs:
                rm(path + "\\" + s)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass
    rm(USER_CLASSES + r"\CLSID\%s" % CLSID)
    rm(USER_CLASSES + r"\PAD.Controller")
    print("PAD.Controller for this user: removed (the machine-wide one again)", flush=True)


# ------------------------------------------------------------------ one table --
def play_one(vpx, tables_dir, name, balls, wait_attach, wait_ball):
    path = os.path.join(tables_dir, name)
    title = vpxsetup.patched_title(tables_dir, name) or ""
    platform = padvpx.platform_of(title) if title else "spike2"
    rec = {"name": name, "title": title, "platform": platform, "errors": [], "balls": 0,
           "attached_s": None, "verdict": ""}
    log = padcontroller.LOG
    mark = log_size(log)
    t0 = time.monotonic()
    print("\n== %s (%s, %s)" % (name, title or "no title", platform), flush=True)
    proc = subprocess.Popen([os.path.join(vpx, "VPinballX64.exe"), "-play", path], cwd=vpx)
    pids = {proc.pid}
    attached = False
    try:
        # the table loads, the patch starts the game, the controller attaches
        deadline = time.monotonic() + wait_attach
        while time.monotonic() < deadline:
            pids |= set(vpx_pids())
            for title_, text in error_dialogs(pids):
                rec["errors"].append("%s: %s" % (title_, text))
            if rec["errors"]:
                break
            tail = log_tail(log, mark)
            if "attached to " in tail:
                attached = True
                rec["attached_s"] = round(time.monotonic() - t0)
                break
            if "failed:" in tail and "Run(" in tail:
                rec["errors"].append(tail[tail.index("Run("):].splitlines()[0])
                break
            if proc.poll() is not None and not vpx_pids():
                rec["errors"].append("Visual Pinball exited (rc %s)" % proc.returncode)
                break
            time.sleep(1)
        if not rec["errors"] and not attached:
            rec["errors"].append("the controller did not attach within %d s" % wait_attach)
        if attached:
            print("   attached after %d s" % rec["attached_s"], flush=True)
            time.sleep(8)                               # the game's attract settles
            hwnd = player_window(pids)
            if hwnd is None:
                rec["errors"].append("no Visual Pinball Player window")
            else:
                focus(hwnd)
                press("5")
                time.sleep(0.6)
                press("5")
                time.sleep(1.5)
                press("1")
                served = 0
                plunged = False
                deadline = time.monotonic() + wait_ball * balls
                while time.monotonic() < deadline:
                    for title_, text in error_dialogs(pids):
                        rec["errors"].append("%s: %s" % (title_, text))
                    if rec["errors"]:
                        break
                    tail = log_tail(log, mark)
                    n = sol_pulses(tail)
                    if n > served:
                        served = n
                        print("   ball %d served" % served, flush=True)
                        if served >= balls:
                            break
                        plunged = False
                    if served and not plunged:
                        time.sleep(3)
                        focus(hwnd)
                        press("enter", hold=1.0)           # plunge; a drain brings the next
                        plunged = True
                    time.sleep(1)
                rec["balls"] = served
                if served < balls and not rec["errors"]:
                    rec["errors"].append("%d of %d balls served within %d s" % (served, balls, wait_ball * balls))
    finally:
        # the player window closed cleanly: the controller stops the run it started
        hwnd = player_window(pids)
        if hwnd is not None:
            u32.PostMessageW(ctypes.c_void_p(hwnd), WM_CLOSE, 0, 0)
        for h, _t, cls, pid in windows():
            if pid in pids and cls == "#32770":
                u32.PostMessageW(ctypes.c_void_p(h), WM_CLOSE, 0, 0)
        end = time.monotonic() + 40
        while time.monotonic() < end and vpx_pids():
            time.sleep(1)
        if vpx_pids():
            subprocess.run(["taskkill", "/F", "/IM", "VPinballX64.exe"], capture_output=True, timeout=30)
            rec["errors"].append("Visual Pinball had to be killed")
        if title:
            try:
                padvpx.stop(title)                       # whatever the run left
            except Exception:                           # noqa: BLE001
                pass
        time.sleep(4)
    rec["verdict"] = "ok" if not rec["errors"] else "FAIL"
    print("   %s%s" % (rec["verdict"], (": " + "; ".join(rec["errors"])) if rec["errors"] else
                       " (%d balls)" % rec["balls"]), flush=True)
    return rec


def main(argv):
    opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else d  # noqa: E731
    only = [w.lower() for w in (opt("--only") or "").split(",") if w]
    balls = int(opt("--balls", 2))
    wait_attach = int(opt("--wait-attach", 150))
    wait_ball = int(opt("--wait-ball", 150))
    out = opt("--out")
    if sys.platform != "win32":
        print("Windows only")
        return 2
    vpx = vpxsetup.find_vpx()
    tables_dir = vpxsetup.vpx_tables_dir()
    names = sorted(n for n in os.listdir(tables_dir or ".") if n.lower().endswith("(pad).vpx")) if tables_dir else []
    if only:
        names = [n for n in names if any(w in n.lower() for w in only)]
    if "--list" in argv:
        for n in names:
            t = vpxsetup.patched_title(tables_dir, n) or ""
            print("%-70s %-20s %s" % (n, t, padvpx.platform_of(t) if t else ""))
        return 0
    if not vpx:
        print("Visual Pinball is not set up (the tab's state)")
        return 2
    if vpx_pids():
        print("Visual Pinball is open: close it first (never run this while someone is playing)")
        return 2
    print("%d tables in %s; Visual Pinball %s; %d balls each" % (len(names), tables_dir, vpx, balls), flush=True)
    if "--this-kit" in argv:
        register_this_kit()
    results = []
    try:
        for n in names:
            results.append(play_one(vpx, tables_dir, n, balls, wait_attach, wait_ball))
            if out:
                json.dump({"tables": results, "kit": KIT}, open(out, "w", encoding="utf-8"), indent=1)
    finally:
        if "--this-kit" in argv:
            unregister_this_kit()
    print("\n%-62s %-18s %-7s %-6s %s" % ("table", "title", "attach", "balls", "verdict"))
    for r in results:
        print("%-62s %-18s %-7s %-6s %s" % (r["name"][:62], r["title"][:18], r["attached_s"] if r["attached_s"] is not None else "-",
                                           r["balls"], r["verdict"] + (": " + "; ".join(r["errors"]) if r["errors"] else "")))
    bad = sum(1 for r in results if r["verdict"] != "ok")
    print("\n%d of %d played %d ball%s; %d failed" % (len(results) - bad, len(results), balls, "" if balls == 1 else "s", bad))
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
