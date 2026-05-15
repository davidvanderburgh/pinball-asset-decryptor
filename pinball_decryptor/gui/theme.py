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
        "tooltip_bg": "#404040", "tooltip_fg": "#cccccc",
    },
    "light": {
        "bg": "#f5f5f5", "fg": "#1e1e1e", "field_bg": "#ffffff",
        "select_bg": "#0078d7", "accent": "#0066cc", "success": "#2e7d32",
        "error": "#c62828", "timestamp": "#757575", "gray": "#888888",
        "trough": "#d0d0d0", "border": "#bbbbbb", "button": "#e0e0e0",
        "tab_selected": "#ffffff", "link": "#0066cc",
        "tooltip_bg": "#ffffe0", "tooltip_fg": "#1e1e1e",
    },
}


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
