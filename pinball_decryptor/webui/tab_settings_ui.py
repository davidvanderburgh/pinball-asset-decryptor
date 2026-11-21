"""The Save settings / Load settings menu items of the Images, Audio and Video
tabs (PAD-300): each tab's RPCs hand their own folder, slots and sidecar
writer to these.  The file format and the merge are
:mod:`..core.tab_settings`; Text has its own pair in ``tabs/text.py``."""

import os
import re

from . import compat
from ..core import staged_changes
from ..core import tab_settings as TS

TITLES = {"images": "Images", "audio": "Audio", "video": "Video"}


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _stem(assets_dir, kind):
    name = os.path.basename(os.path.normpath(assets_dir or "")) or "project"
    return re.sub(r'[\\/:*?"<>|]+', "_", "%s %s settings" % (name, kind))


def save_media(tab, kind, assets_dir, scanned, flush):
    """Save to a file: *flush* writes the tab's state to the sidecar first,
    then the tab's sections go to a file the user names.  Returns the path,
    or None."""
    title = "Save %s settings" % kind
    if not scanned or not assets_dir or not os.path.isdir(assets_dir):
        compat.messagebox.showinfo(
            title, "Scan a project folder on this tab first.")
        return None
    flush()
    path = tab.window.ask_save(
        "%s_settings_file" % kind, "Save this tab's settings to a file",
        initialfile=_stem(assets_dir, kind) + ".json",
        filetypes=[("PAD %s settings" % kind, "*.json")],
        defaultextension=".json")
    if not path:
        return None
    try:
        n = TS.export_media(staged_changes.load(assets_dir), kind, path)
    except OSError as e:
        compat.messagebox.showerror(title, str(e))
        return None
    tab.log("%s: saved the settings of %s to %s"
            % (TITLES[kind], _plural(n, "slot"), path), "info")
    return path


def load_media(tab, kind, assets_dir, slots, running, flush, rescan,
               path=None):
    """Load from a file: merge a settings file into this project's sidecar
    (asking first when it changes picks made here) and re-scan so the tab
    shows them.  Returns ``{slots, missing, gone}``, or None."""
    title = "Load %s settings" % kind
    if running:
        compat.messagebox.showinfo(
            title, "Wait for the current job to finish, then load.")
        return None
    if not slots or not assets_dir or not os.path.isdir(assets_dir):
        compat.messagebox.showinfo(
            title, "Scan a project folder on this tab first.")
        return None
    flush()
    if not path:
        path = tab.window.ask_open(
            "%s_settings_file" % kind, "Load settings from a file",
            filetypes=[("PAD %s settings" % kind, "*.json"),
                       ("All files", "*.*")])
    if not path:
        return None
    name = os.path.basename(path)
    try:
        doc = TS.read(path, kind)
        res = TS.merge_media(staged_changes.load(assets_dir), doc, kind,
                             slots)
    except (TS.TabSettingsError, OSError) as e:
        compat.messagebox.showinfo(title, str(e))
        return None
    if not res.slots and not res.themes:
        compat.messagebox.showinfo(
            title, "None of the slots in %s are on this card, so nothing "
            "was loaded." % name if res.missing else
            "%s holds no slot settings, so nothing was loaded." % name)
        return None
    if res.clash and not compat.messagebox.askyesno(
            title, "%s already %s a different replacement picked here. "
            "Loading puts the file's in %s place. Go ahead?"
            % (_plural(len(res.clash), "slot"),
               "has" if len(res.clash) == 1 else "have",
               "its" if len(res.clash) == 1 else "their")):
        return None
    staged_changes.save(assets_dir, res.data)
    if res.themes:
        # the file's themes (Simon, 2026-11-20) show in the theme picker at once
        sets = tab.window.service("imgsets") if hasattr(tab.window, "service") else None
        if sets is not None and hasattr(sets, "publish"):
            sets.publish()
    cb = tab.window.cb.get("on_folder_state_written")
    if cb is not None:
        cb(assets_dir)
    tab.log("%s: loaded the settings of %s from %s"
            % (TITLES[kind], _plural(len(res.slots), "slot"), path), "info")
    # A fresh scan reads the sidecar back the way opening the project does,
    # and logs each pick whose file is not on this PC.
    tab.window._relink_hint_for = None
    tab.invalidate_asset_scans(rescan_visible=False)
    rescan()
    words = "Loaded the settings of %s from %s." % (
        _plural(len(res.slots), "slot"), name)
    if res.themes:
        words += " Its themes (%d besides theme 1) take this project's place." % res.themes
    if res.missing:
        words += " %s in the file %s not on this card and %s left out." % (
            _plural(len(res.missing), "slot"),
            "is" if len(res.missing) == 1 else "are",
            "was" if len(res.missing) == 1 else "were")
    if res.gone:
        words += ("\n\n%s %s not on this PC. The Log lists them; Project > "
                  "Relink moved files... can point them at where they are "
                  "now." % (_plural(len(res.gone), "replacement file"),
                            "is" if len(res.gone) == 1 else "are"))
    compat.messagebox.showinfo(title, words)
    return {"slots": len(res.slots), "missing": len(res.missing),
            "gone": len(res.gone)}
