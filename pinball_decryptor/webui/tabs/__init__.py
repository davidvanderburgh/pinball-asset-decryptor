"""The tabs, in rail order.

Each entry names a module of this package that defines ``TAB``, a
:class:`~.base.TabService` subclass.  A module that is missing or fails to
import leaves a placeholder in the rail (so one broken tab never takes the
app down) and the failure goes to the session log.
"""

import importlib
import logging

from .base import TabService

log = logging.getLogger(__name__)

#: (module, ns, Tk stable key, rail label, rail group, icon)
TABS = (
    ("extract", "extract", "Extract", "Extract", "Card", "extract"),
    ("audio", "audio", "Replace Audio", "Audio", "Replace", "audio"),
    ("video", "video", "Replace Video", "Video", "Replace", "video"),
    ("images", "images", "Replace Images", "Images", "Replace", "images"),
    ("text", "text", "Replace Text", "Text", "Replace", "text"),
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


def load_tab_classes():
    classes = []
    for module, ns, key, label, group, icon in TABS:
        try:
            mod = importlib.import_module("%s.%s" % (__name__, module))
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
