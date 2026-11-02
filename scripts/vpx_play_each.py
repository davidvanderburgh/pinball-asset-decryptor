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
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu", "vpx")
sys.path.insert(0, KIT)

import padcontroller  # noqa: E402
import padlaunch  # noqa: E402
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

    WM_GETTEXTLENGTH, WM_GETTEXT = 0x000E, 0x000D

    def cb(h, _l):
        # WM_GETTEXT, not GetWindowText: an Edit box's text in another
        # process (the error's own lines) comes only through the message
        n = u32.SendMessageW(ctypes.c_void_p(h), WM_GETTEXTLENGTH, 0, 0)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.SendMessageW(ctypes.c_void_p(h), WM_GETTEXT, n + 1, buf)
            text = " ".join(buf.value.split())
            if text and text not in ("OK", "Cancel", "Continue", "Stop") and not text.startswith("Install a script debugger"):
                parts.append(text)
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
        # "Preparing Table" is the progress box every load shows, not an error
        if pid in pids and cls == "#32770" and not title.startswith("Preparing Table"):
            out.append((title, dialog_text(h)))
    return out


def kill_stale_controllers():
    """PAD.Controller servers left from a killed Visual Pinball: a COM local
    server outlives a client that never released it, keeps polling, attaches
    to the NEXT run on the slot and hands it its old table's switches (the
    first pass: Batman's trough switches went into Aerosmith's game)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name = 'pythonw.exe' or Name = 'python.exe'\" "
          "| Where-Object { $_.CommandLine -like '*localserver.py*' } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60).stdout
    except Exception:                                       # noqa: BLE001
        return 0
    pids = [int(line) for line in out.split() if line.strip().isdigit()]
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
    if pids:
        print("   killed %d stale PAD.Controller server%s" % (len(pids), "" if len(pids) == 1 else "s"), flush=True)
    return len(pids)


def main_window(pids):
    """Visual Pinball's editor window: closing it ends the player and quits."""
    for h, title, cls, pid in windows():
        if pid in pids and title.startswith("Visual Pinball - ["):
            return h
    return None


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
    """The player window to the foreground, and really there (Visual Pinball
    reads the keys through DirectInput: a press lands only on the foreground
    window). Windows refuses SetForegroundWindow to a process that did not
    get the last input; a tap on Alt first is the classic way round it."""
    for _ in range(6):
        u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        time.sleep(0.3)
        if u32.GetForegroundWindow() == hwnd:
            return True
        u32.keybd_event(0x12, 0, 0, 0)                      # Alt down / up
        u32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)
    return u32.GetForegroundWindow() == hwnd


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


def trough_solenoid(title):
    """The small number the map gives the trough's kicker: 1 in the shadow
    maps, whatever the older vpxmap shape names TROUGH (The Beatles: 10, its
    Seawitch numbering), 1 when the map cannot be read."""
    try:
        info = padvpx.maps().get(title) or {}
        m = json.load(open(info["map"], encoding="utf-8"))
        for num, v in (m.get("solenoids") or {}).items():
            if num.isdigit() and isinstance(v, dict) and "trough" in (v.get("name") or "").lower()                     and "kick" not in (v.get("name") or "").lower().replace("up-kicker", "trough"):
                return int(num)
        for num, v in (m.get("solenoids") or {}).items():
            if num.isdigit() and isinstance(v, dict) and "trough" in (v.get("name") or "").lower():
                return int(num)
    except Exception:                                       # noqa: BLE001
        pass
    return 1


def rig_script(slot, title, script, timeout):
    """`script` in the slot's own WSL environment (the app's launch shape),
    in the rig folder with rigjob.sh sourced and this title's switch list."""
    launch = padlaunch.Launch(title, "")
    launch.slot = slot
    head, _root = launch.head()
    env = launch.board_env() + ["PAD_SLOT=%d" % slot]
    pre = ("cd %s && . ./rigjob.sh && LIST=$ROOT/dump/tables/%s/switch_list.txt && "
           "JOB_OUT=/tmp/vpxplay.$$ && mkdir -p $JOB_OUT && JOB_T0=$(date +%%s) && " % (launch.rig_wsl, title))
    try:
        return subprocess.run(head + env + ["bash", "-c", pre + script], capture_output=True, text=True, timeout=timeout)
    except Exception as exc:                                # noqa: BLE001
        print("   rig script failed: %s" % exc, flush=True)
        return None


def wait_attract(slot, title, wait_s):
    """Until the game is in attract mode (the rig library's job_wait_attract:
    the controller attaches at the shim's first frame, a minute before the
    game has left Tech Alerts; a first boot's Guided Setup is walked on the
    way). True when it is."""
    out = rig_script(slot, title, "job_wait_attract %d && echo ATTRACT" % wait_s, wait_s + 90)
    if out is None:
        return False
    for line in (out.stdout or "").splitlines():
        if "attract at" in line or "Guided Setup" in line or "no attract" in line:
            print("   rig: " + line.split("s ", 1)[-1].strip(), flush=True)
    return "ATTRACT" in (out.stdout or "")


def guided_setup_walk(slot, title):
    """Stern's Guided Setup, on a title's first boot in this rig, swallows
    coins and Start (the rig's NVRAM is per title). The rig library's
    job_guided_setup walks it: service Plus down to Save & Exit, read off a
    frame of the game's screen (menurow.py), then Select. True when it did."""
    launch = padlaunch.Launch(title, "")
    launch.slot = slot
    head, _root = launch.head()
    env = launch.board_env() + ["PAD_SLOT=%d" % slot]
    script = ("cd %s && . ./rigjob.sh && LIST=$ROOT/dump/tables/%s/switch_list.txt && "
              "job_guided_setup 2 && echo WALKED" % (launch.rig_wsl, title))
    try:
        out = subprocess.run(head + env + ["bash", "-c", script], capture_output=True, text=True, timeout=240)
    except Exception as exc:                                # noqa: BLE001
        print("   guided setup walk failed: %s" % exc, flush=True)
        return False
    return "WALKED" in (out.stdout or "")


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
    trough = trough_solenoid(title) if title else 1
    log = padcontroller.LOG
    kill_stale_controllers()
    if platform == "spike1":
        # one Spike 1 rig: a run of the kit's left from an earlier table (or a
        # hand try from the tab) is stopped first, or the controller refuses
        try:
            other = padlaunch.Spike1Launch(title, "").other_run()
        except Exception:                                   # noqa: BLE001
            other = None
        if other and other.get("game"):
            print("   the Spike 1 rig is running %s: stopping it" % other["game"], flush=True)
            try:
                padvpx.stop(other["game"])
            except Exception:                               # noqa: BLE001
                pass
            time.sleep(3)
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
                m = re.search(r"attached to rig board slot (\d+)", tail)
                slot = int(m.group(1)) if m else None
                mark += len(tail.encode("utf-8", "replace"))   # the balls are counted from here
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
                def try_start(wait_s=25):
                    """Coins and Start to the player; the trough's kicks within
                    wait_s, counted from the Start press: a kick before it is
                    the game's own trough check at boot (John Wick's ball sat
                    in the lane through attract and Start was ignored with a
                    ball missing), so whatever is in the lane is plunged and
                    given time to come home first."""
                    nonlocal mark
                    focus(hwnd)
                    press("enter", hold=1.0)
                    time.sleep(20)
                    focus(hwnd)
                    # a Spike 1 game counted no credit for an 80 ms coin pulse
                    # (Can Crusher: CREDITS 0 on the DMD after two): longer, and three
                    coins = 3 if platform == "spike1" else 2
                    for _ in range(coins):
                        press("5", hold=0.3 if platform == "spike1" else 0.08)
                        time.sleep(0.8)
                    time.sleep(1.5)
                    mark = log_size(log)
                    press("1", hold=0.3)
                    end = time.monotonic() + wait_s
                    while time.monotonic() < end:
                        n = sol_pulses(log_tail(log, mark), trough)
                        if n or error_dialogs(pids):
                            return n
                        time.sleep(1)
                    return 0
                # the game to attract mode first (Tech Alerts, a first boot's
                # Guided Setup), then coins and Start; a second try walks a
                # Guided Setup that came up late
                if slot is not None:
                    if not wait_attract(slot, title, wait_attach):
                        rec["errors"].append("the game did not reach attract mode within %d s" % wait_attach)
                else:
                    time.sleep(120)                          # Spike 1: no status word; attract ~110 s after the rig is up
                served = 0 if rec["errors"] else try_start()
                if not served and slot is not None and not rec["errors"] and not error_dialogs(pids):
                    print("   no game at Start: looking for Guided Setup", flush=True)
                    if guided_setup_walk(slot, title):
                        rec.setdefault("notes", []).append("Guided Setup walked (the title's first boot here)")
                        time.sleep(6)
                    served = try_start()
                if served:
                    print("   ball %d served" % served, flush=True)
                plunged = False
                deadline = time.monotonic() + wait_ball * balls
                while time.monotonic() < deadline:
                    for title_, text in error_dialogs(pids):
                        rec["errors"].append("%s: %s" % (title_, text))
                    if rec["errors"]:
                        break
                    tail = log_tail(log, mark)
                    n = sol_pulses(tail, trough)
                    if n > served:
                        served = n
                        print("   ball %d served" % served, flush=True)
                        plunged = False
                    if served >= balls:
                        break
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
        # Visual Pinball closed cleanly (its editor window: the player ends and
        # the controller stops the run it started), else killed - then the
        # controller server it leaves is killed too, before the next table
        for h, _t, cls, pid in windows():
            if pid in pids and cls == "#32770":
                u32.PostMessageW(ctypes.c_void_p(h), WM_CLOSE, 0, 0)
        hwnd = main_window(pids) or player_window(pids)
        if hwnd is not None:
            u32.PostMessageW(ctypes.c_void_p(hwnd), WM_CLOSE, 0, 0)
        end = time.monotonic() + 40
        while time.monotonic() < end and vpx_pids():
            time.sleep(1)
        if vpx_pids():
            subprocess.run(["taskkill", "/F", "/IM", "VPinballX64.exe"], capture_output=True, timeout=30)
            rec.setdefault("notes", []).append("Visual Pinball had to be killed")
            time.sleep(2)
            kill_stale_controllers()
        if title:
            try:
                padvpx.stop(title)                       # whatever the run left
            except Exception:                           # noqa: BLE001
                pass
        time.sleep(4)
    # ok: every asked ball; partial: a game played but a ball never came home
    # within the wait (nothing plays the table); FAIL: an error, or no ball
    if rec["errors"] and rec["balls"] and len(rec["errors"]) == 1 and "balls served within" in rec["errors"][0]:
        rec.setdefault("notes", []).append(rec["errors"].pop())
    rec["verdict"] = "FAIL" if rec["errors"] else "ok" if rec["balls"] >= balls else "partial"
    print("   %s%s" % (rec["verdict"], (": " + "; ".join(rec["errors"])) if rec["errors"] else
                       " (%d ball%s%s)" % (rec["balls"], "" if rec["balls"] == 1 else "s",
                                           "; " + "; ".join(rec.get("notes", [])) if rec.get("notes") else "")), flush=True)
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
    kill_stale_controllers()
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
    bad = sum(1 for r in results if r["verdict"] == "FAIL")
    part = sum(1 for r in results if r["verdict"] == "partial")
    print("\n%d of %d played %d ball%s, %d one ball; %d failed" % (len(results) - bad - part, len(results), balls,
                                                                  "" if balls == 1 else "s", part, bad))
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
