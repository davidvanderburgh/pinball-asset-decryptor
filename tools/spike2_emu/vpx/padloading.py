#!/usr/bin/env python3
"""padloading.py - the window a table's game shows while it starts (PAD-940).

    pythonw padloading.py <title> <launch log> <status file> [--expect S] [--parent PID]
                          [--rect X Y W H]

--rect pins it there instead (a test's spot, off the desktop: it never
follows a game window then).

A run the controller starts for a table takes a minute or more before the
game's own window shows anything: WSL comes up, the card is cached and
mounted (the first boot of a title on a slot is the slow one), the renderer
opens a black window and the game boots into it. Visual Pinball sat there
with nothing to say it was coming (David, 2026-11-02: "we feel that it's
broken"). This window stands where the game's screen goes - on top of it once
it opens - with a progress bar and the step the run is on, read from the
run's own log, and goes when the game is up. It lets the mouse through
(PAD-962): a press on it is a press on the game's window under it, so that
window drags and resizes as ever while this one follows it.

The controller (padcontroller.Bridge) starts it with the run and writes the
status file: `up` closes it; `failed <why>` shows why for a few seconds,
then closes it. It also closes when the controller's process is gone, and
never takes the focus: Visual Pinball pauses the table when it loses it.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

#: the run's steps as its log shows them: (the line's start, how far the bar
#: is at least once it is seen, what the window says). The last one seen wins.
STEPS = (
    ("[card] evicting", 0.10, "Making room for the card image"),
    ("[card] caching", 0.12, "Reading the card image"),
    ("[card] mounting", 0.30, "Reading the card image"),
    ("[card] title:", 0.40, "Getting the game ready"),
    ("[watch] cfg ", 0.45, "Getting the game ready"),
    ("[watch] starting renderer", 0.60, "Opening the game's screen"),
    ("[watch] game window opened", 0.65, "Opening the game's screen"),
    ("[watch] starting ", 0.70, "Starting the game"),
    ("[watch] waiting for the game", 0.75, "Starting the game"),
    ("[watch] running.", 0.80, "Starting the game"),
)
FIRST = "Starting the emulator's Linux"

#: how long a failure stays up; how long to wait at most (the controller's
#: own START_TIMEOUT_S is 420)
FAILED_S = 8.0
#: how long after its first show no window may take the foreground (main)
LOCK_S = 2.0
#: how often it moves to where the game's window is now
FOLLOW_MS = 40
CAP_S = 480.0


def step_of(text):
    """(floor, words) for the run's log so far; before any of it, Linux."""
    floor, words = 0.0, FIRST
    for line in text.splitlines():
        for start, f, w in STEPS:
            if line.startswith(start):
                floor, words = f, w
                break
    return floor, words


def progress(floor, elapsed, expect):
    """The bar: the time it took last time sets the pace, the steps seen set
    a floor, and it never reads done until the game is."""
    pace = elapsed / expect if expect > 0 else 0.0
    return min(0.95, max(floor, pace))


def name_of(title):
    """The table's own name from its map, else the title in words."""
    try:
        import padvpx
        import json
        info = padvpx.maps().get(title) or {}
        name = (json.load(open(info["map"], encoding="utf-8")).get("table") or {}).get("name")
        if name:
            return name
    except Exception:                                       # noqa: BLE001
        pass
    up = {"le": "LE", "pro": "Pro", "se": "SE"}
    return " ".join(up.get(w, w.capitalize()) for w in (title or "the game").split("_"))


def read_status(path):
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def parent_alive(pid):
    if not pid or sys.platform != "win32":
        return True
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))              # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259                   # STILL_ACTIVE


def first_rect():
    """Where the game's screen will open: the display setting (display.conf),
    else the kit's `lcd` placement, as the controller places it."""
    import padcontroller
    import padisplay
    import padlaunch
    try:
        line = padisplay.resolve(padisplay.load())
        if line:
            kv = dict(t.split("=", 1) for t in line.split()[1:])
            return int(kv["x"]), int(kv["y"]), int(kv["w"]), int(kv["h"])
    except Exception:                                       # noqa: BLE001
        pass
    return padcontroller.lcd_rect(padlaunch.kit_load().get("lcd") or {}, padcontroller.monitors())


def log_tail(path, start):
    try:
        with open(path, "rb") as f:
            f.seek(start)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    title, logfile, status = argv[0], argv[1], argv[2]
    expect = float(argv[argv.index("--expect") + 1]) if "--expect" in argv else 45.0
    parent = int(argv[argv.index("--parent") + 1]) if "--parent" in argv else 0
    pinned = (tuple(int(v) for v in argv[argv.index("--rect") + 1:argv.index("--rect") + 5])
              if "--rect" in argv else None)
    try:
        start = os.path.getsize(logfile)                    # the log is appended to, run after run
    except OSError:
        start = 0
    import tkinter as tk
    import padcontroller
    padcontroller.dpi_aware()
    # a process just started may take the foreground, and Tk takes it when
    # its window is first created and again ~0.4 s after it is first shown
    # (measured), withdrawn, WS_EX_NOACTIVATE or not: Visual Pinball would
    # lose it and pause. So no SetForegroundWindow anywhere until LOCK_S
    # after the first show - and only that long: the controller hands the
    # player the focus back with it once the game's window opens.
    user32 = __import__("ctypes").windll.user32 if sys.platform == "win32" else None
    locked = [bool(user32 and user32.LockSetForegroundWindow(1))]          # LSFW_LOCK

    def unlock():
        if locked[0]:
            user32.LockSetForegroundWindow(2)                               # LSFW_UNLOCK
            locked[0] = False

    BG, INK, MUTED, BAR, TROUGH, WARN = "#15171a", "#e9eae7", "#8b9196", "#e8a33d", "#2a2f35", "#e5734a"
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.configure(bg=BG)
    root.title("PAD - starting %s" % title)
    box = tk.Frame(root, bg=BG)
    box.place(relx=0.5, rely=0.5, anchor="center")
    head = tk.Label(box, text=name_of(title), bg=BG, fg=INK, font=("Segoe UI Semibold", 20))
    head.pack(pady=(0, 6))
    sub = tk.Label(box, text="Starting the game behind the table", bg=BG, fg=MUTED, font=("Segoe UI", 11),
                   wraplength=640, justify="center")
    sub.pack(pady=(0, 18))
    bar = tk.Canvas(box, width=420, height=8, bg=TROUGH, highlightthickness=0, bd=0)
    bar.pack()
    fill = bar.create_rectangle(0, 0, 0, 8, fill=BAR, width=0)
    step = tk.Label(box, text=FIRST + "…", bg=BG, fg=INK, font=("Segoe UI", 11))
    step.pack(pady=(14, 0))
    clock = tk.Label(box, text="", bg=BG, fg=MUTED, font=("Segoe UI", 10))
    clock.pack(pady=(4, 0))

    t0 = time.monotonic()
    state = {"rect": None, "failed": 0.0, "hwnd": 0}

    def put(rect):
        """There, on top, WITHOUT taking the focus from Visual Pinball (the
        foreground lock above holds while Tk shows it)."""
        if rect == state["rect"]:
            return
        state["rect"] = rect
        x, y, w, h = rect
        root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        root.deiconify()
        root.attributes("-topmost", True)
        if sys.platform == "win32":
            # styled once it is mapped: Tk makes its frame window anew when
            # a withdrawn override-redirect window is first shown, and the
            # one styled before that was thrown away (PAD-962 found the
            # styles below had never landed)
            root.update_idletasks()
            hwnd = int(root.wm_frame(), 16)                 # Tk's own frame window
            state["hwnd"] = hwnd
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            # PAD-962: layered + transparent is click-through - it stood
            # over the game's window and took every press, so that window
            # could not be dragged until the game was up. A layered window
            # shows nothing until it is given its alpha (opaque here).
            WS_EX_LAYERED, WS_EX_TRANSPARENT, LWA_ALPHA = 0x00080000, 0x00000020, 0x2
            want = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TRANSPARENT
            had = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if had & want != want:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, had | want)
                user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)

    def tick():
        now = time.monotonic()
        said = read_status(status)
        if said == "up" or not parent_alive(parent) or now - t0 > CAP_S:
            root.destroy()
            return
        if said.startswith("failed"):
            if not state["failed"]:
                state["failed"] = now
                step.configure(text="The game did not start.", fg=WARN)
                bar.pack_forget()
                sub.configure(text=said[len("failed"):].strip() or "See the Visual Pinball tab's log.")
                clock.configure(text="")
            if now - state["failed"] > FAILED_S:
                root.destroy()
                return
            root.after(250, tick)
            return
        floor, words = step_of(log_tail(logfile, start))
        pct = progress(floor, now - t0, expect)
        bar.coords(fill, 0, 0, int(420 * pct), 8)
        step.configure(text=words + "…")
        secs = int(now - t0)
        clock.configure(text="%d s" % secs + (" (about %d s last time)" % expect if "--expect" in argv else ""))
        state.setdefault("shown", now)
        if now - state["shown"] > LOCK_S:
            unlock()
        if state["hwnd"]:
            padcontroller.raise_window(state["hwnd"], True)     # over the game's window, which is on top too
        root.after(250, tick)

    def follow():
        """Over the game's own window once it is there (it is black until
        the game's first picture), else where it will open - often enough
        to keep up with a hand drag of that window (PAD-962)."""
        if state["failed"]:
            return
        rect = pinned
        if rect is None and sys.platform == "win32":
            try:
                lcd = padcontroller.find_lcd_window()
                if lcd:
                    rect = tuple(padcontroller.window_rect(lcd))
                    rect = rect if rect[2] > 0 and rect[3] > 0 else None
            except Exception:                               # noqa: BLE001
                rect = None
        if rect is None and "first" not in state:
            state["first"] = first_rect()
        put(rect or state["first"])
        root.after(FOLLOW_MS, follow)

    def watchdog():
        """The window goes whatever Tk's loop is doing: one run in a dozen
        under pythonw.exe stopped calling tick() (no exception, idle in
        mainloop) and stood on top until it was killed. Off Tk's thread, so
        it ends the process itself."""
        failed_at = 0.0
        while True:
            time.sleep(0.5)
            now = time.monotonic()
            said = read_status(status)
            if said.startswith("failed") and not failed_at:
                failed_at = now
            if (said == "up" or not parent_alive(parent) or now - t0 > CAP_S
                    or (failed_at and now - failed_at > FAILED_S + 1.0)):
                unlock()
                os._exit(0)
    import threading
    threading.Thread(target=watchdog, daemon=True).start()
    root.after(0, follow)
    root.after(0, tick)
    try:
        root.mainloop()
    finally:
        unlock()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
