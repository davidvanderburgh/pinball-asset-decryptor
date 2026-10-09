"""The tabs, in rail order.

Each entry names a module of this package that defines ``TAB``, a
:class:`~.base.TabService` subclass.  A module that is missing or fails to
import leaves a placeholder in the rail (so one broken tab never takes the
app down) and the failure goes to the session log.
"""

import importlib
import logging
import sys
import time

from .base import TabService

log = logging.getLogger(__name__)

#: (module, ns, Tk stable key, rail label, rail group, icon)
TABS = (
    ("card", "card", "Select Card", "Select card", "Card", "sd"),
    ("extract", "extract", "Extract", "Extract", "Card", "extract"),
    ("audio", "audio", "Replace Audio", "Audio", "Replace", "audio"),
    ("video", "video", "Replace Video", "Video", "Replace", "video"),
    ("images", "images", "Replace Images", "Images", "Replace", "images"),
    ("text", "text", "Replace Text", "Text", "Replace", "text"),
    # PAD-251: the scene editor, a page of its own (it was a floating window)
    ("scenes", "scenes", "Scenes", "Scenes", "Replace", "scenes"),
    # PAD-305: the colour correction a build applies for the machine's display
    ("color", "color", "Color Profile", "Color profile", "Replace",
     "palette"),
    ("modes", "modes", "Modes", "Modes", "Make", "modes"),
    ("defaults", "defaults", "Default Settings", "Defaults", "Make",
     "defaults"),
    ("write", "write", "Write", "Write", "Build", "write"),
    ("multiboot", "multiboot", "Multi-boot", "Multi-boot", "Build",
     "multiboot"),
    ("modpack", "modpack", "Mod Pack", "Mod Pack", "Build", "modpack"),
    ("partitions", "partitions", "Partition Explorer", "Partitions",
     "Inspect", "partitions"),
    ("compare", "compare", "Compare", "Compare", "Inspect", "compare"),
    ("emulate", "emulate", "Emulate", "Emulate", "Play", "emulate"),
    ("emulate_jjp", "emulate_jjp", "Emulate JJP", "Emulate", "Play",
     "emulate"),
    ("emulate_spike1", "emulate_spike1", "Emulate Spike1", "Emulate",
     "Play", "emulate"),
    ("emulate_ap", "emulate_ap", "Emulate AP", "Emulate", "Play",
     "emulate"),
    ("emulate_bof", "emulate_bof", "Emulate BoF", "Emulate", "Play",
     "emulate"),
    ("emulate_dp", "emulate_dp", "Emulate DP", "Emulate", "Play",
     "emulate"),
    ("emulate_spooky", "emulate_spooky", "Emulate Spooky", "Emulate", "Play",
     "emulate"),
    ("emulate_pb", "emulate_pb", "Emulate PB", "Emulate", "Play",
     "emulate"),
    # Not a tab: the app-wide menus, windows and banners (settings, help,
    # projects, updates).  Its key is empty, so the rail never shows it.
    ("shell_extras", "shellx", "", "", "", ""),
)


def _placeholder(ns, key, label, group, icon, reason):
    return type("Placeholder_%s" % ns, (TabService,), {
        "ns": ns, "key": key, "label": label, "group": group, "icon": icon,
        "placeholder": reason,
        "on_manufacturer": lambda self, mfr: self.set(placeholder=reason),
    })


#: PAD-430: seconds to wait before each retry of a tab whose import hit a
#: file another process holds open.  A virus scanner reading a DLL the update
#: just wrote (numpy's _multiarray_umath) fails the import outright; the lock
#: is gone a moment later, so the tab loads on a retry.
_LOCKED_RETRY_WAITS = (0.5, 1.0, 2.0, 4.0)


def _file_locked(exc):
    """True when *exc* (or anything it wraps) is a Windows sharing violation."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "winerror", None) == 32:
            return True
        text = str(exc)
        if "being used by another process" in text or "WinError 32" in text:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _import_tab(name):
    """Import the tab module *name*, retrying while a file it needs is locked."""
    for wait in _LOCKED_RETRY_WAITS + (None,):
        before = set(sys.modules)
        try:
            return importlib.import_module(name)
        except Exception as e:                        # noqa: BLE001
            if wait is None or not _file_locked(e):
                raise
            log.warning("tab %s import hit a locked file, retrying in %.1fs:"
                        " %s", name, wait, e)
            # Drop what the failed attempt left half-imported (numpy keeps
            # the submodules it loaded before the DLL), so the retry starts
            # from a clean slate.
            for mod in set(sys.modules) - before:
                sys.modules.pop(mod, None)
            importlib.invalidate_caches()
            time.sleep(wait)


def load_tab_classes():
    classes = []
    for module, ns, key, label, group, icon in TABS:
        try:
            mod = _import_tab("%s.%s" % (__name__, module))
            cls = getattr(mod, "TAB")
            for attr, value in (("ns", ns), ("key", key), ("label", label),
                                ("group", group), ("icon", icon)):
                if not getattr(cls, attr, ""):
                    setattr(cls, attr, value)
        except ModuleNotFoundError as e:
            if e.name != "%s.%s" % (__name__, module):
                log.exception("tab %s failed to import", module)
                cls = _placeholder(ns, key, label, group, icon,
                                   "This tab failed to load: %s" % e)
            else:
                cls = _placeholder(ns, key, label, group, icon,
                                   "This tab is not built yet.")
        except Exception as e:                        # noqa: BLE001
            log.exception("tab %s failed to import", module)
            cls = _placeholder(ns, key, label, group, icon,
                               "This tab failed to load: %s" % e)
        classes.append(cls)
    return classes
