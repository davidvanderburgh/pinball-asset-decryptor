"""Tk theme + platform-font helpers shared by the main window."""

import sys


def platform_font():
    if sys.platform == "win32":
        return "Segoe UI", "Consolas"
    elif sys.platform == "darwin":
        return "SF Pro Text", "Menlo"
    return "sans-serif", "monospace"


THEMES = {
    "dark": {
        "bg": "#2d2d2d", "fg": "#cccccc", "field_bg": "#1e1e1e",
        "select_bg": "#264f78", "accent": "#569cd6", "success": "#6a9955",
        "error": "#f44747", "timestamp": "#808080", "gray": "#808080",
        "trough": "#404040", "border": "#555555", "button": "#404040",
        "tab_selected": "#1e1e1e", "link": "#3794ff",
        "warning": "#d7ba7d",
        "tooltip_bg": "#404040", "tooltip_fg": "#cccccc",
        # Color-coded action buttons: green = go/confirm, red = destructive
        # (abort a run, revert files).  Fill + hover/pressed shade; white
        # text on both.  Muted a step below the log's success/error text
        # colors so a solid button doesn't glow against the dark panel.
        "go_btn": "#2f7d32", "go_btn_hot": "#3f9c44",
        "danger_btn": "#a33636", "danger_btn_hot": "#c24444",
    },
    "light": {
        "bg": "#f5f5f5", "fg": "#1e1e1e", "field_bg": "#ffffff",
        "select_bg": "#0078d7", "accent": "#0066cc", "success": "#2e7d32",
        "error": "#c62828", "timestamp": "#757575", "gray": "#888888",
        "trough": "#d0d0d0", "border": "#bbbbbb", "button": "#e0e0e0",
        "tab_selected": "#ffffff", "link": "#0066cc",
        "warning": "#9a6700",
        "tooltip_bg": "#ffffe0", "tooltip_fg": "#1e1e1e",
        "go_btn": "#2e7d32", "go_btn_hot": "#256a29",
        "danger_btn": "#c62828", "danger_btn_hot": "#a52222",
    },
}


def dark_titlebar(win, is_dark):
    """Match a window's Windows title bar to the theme (DWM immersive dark).

    Tk paints a Toplevel's client area but never its title bar, so in dark
    mode every secondary window opened with a light bar while the main window
    had a dark one (monkeybug batch 16: "dark mode isn't 100% on popups").
    No-op off Windows and on Windows 10 builds without the attribute."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()          # the HWND must exist
        value = ctypes.c_int(1 if is_dark else 0)
        # winfo_id() is the inner client-area HWND; its parent owns the bar.
        inner = win.winfo_id()
        hwnd = ctypes.windll.user32.GetParent(inner) or inner
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20,                   # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def detect_system_theme():
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if value else "dark"
        except Exception:
            return "light"
    elif sys.platform == "darwin":
        try:
            import subprocess as sp
            r = sp.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                       capture_output=True, text=True, timeout=5)
            return "dark" if "Dark" in r.stdout else "light"
        except Exception:
            return "light"
    return "light"
