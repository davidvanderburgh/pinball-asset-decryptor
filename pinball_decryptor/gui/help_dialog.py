"""Per-tab tips window — the header "?" button (monkeybug feedback).

Every working-view tab carries a pile of behaviour that used to live only in
inline grey prose or hover tooltips.  This window collects those tips per tab
so a user can pull up "everything worth knowing about this page" on demand
instead of hunting for hidden hovers.

One window per app (monkeybug round 2): clicking "?" re-uses the open window
instead of stacking a new Toplevel per click, and switching notebook tabs
re-renders the open window for the new tab so the text never goes stale.

Content is deliberately static + manufacturer-agnostic (plugin-specific
behaviours say "where available"); if per-manufacturer help is ever needed,
grow ``HELP_CONTENT`` into a hook on ``Manufacturer`` like ``write_intro``.
"""

import tkinter as tk
from tkinter import ttk

from .theme import THEMES, platform_font


# (title, body) sections per notebook-tab name.  Keys match the tab captions
# exactly (MainWindow._open_tab_help passes the stripped tab text through).
HELP_CONTENT = {
    "Extract": [
        ("Pick a source",
         "Point the input box at a dumped card image / update file. Plugins "
         "with direct-media support also offer a \"From SD card / SSD\" mode "
         "that reads the physical media in a reader (needs Administrator on "
         "Windows)."),
        ("Detection",
         "The \"Detected: …\" badge under the path confirms the game was "
         "recognised. \"Not recognised\" usually means the wrong kind of file "
         "— or a copy that is still in progress; try again once the copy "
         "finishes. If the file belongs to a different manufacturer, the "
         "badge offers a one-click switch."),
        ("What gets extracted",
         "The Audio / Video / Images / Text checkboxes choose which asset "
         "types to pull. Everything lands in the Output Folder, which then "
         "becomes your working assets folder on the Replace, Write and Mod "
         "Pack tabs. These choices (and the auto-name options) are "
         "remembered per manufacturer across sessions."),
        ("Auto-naming",
         "\"Auto-name call-outs\" transcribes speech locally (the first run "
         "downloads a ~75 MB model, after that it works offline). "
         "\"Auto-name music\" fingerprints full-length tracks against the "
         "online AcoustID database — the number after a matched title (e.g. "
         "0.97) is the match confidence. Results are also written to "
         "callouts.csv and music_titles.csv in the output folder. "
         "For better transcriptions at the cost of extra processing time, "
         "raise \"Voice recognition quality\" in the ⚙ settings menu (larger "
         "models are downloaded on first use)."),
        ("Length-prefixed names",
         "\"Length-prefix names\" (where available) leads each extracted "
         "sound's filename with its play length — e.g. "
         "\"01m22s235 - idx0001.wav\" — so sorting by name lines the same "
         "sounds up across firmware versions: slot numbers shift between "
         "releases, play lengths rarely do."),
        ("The baseline",
         "Extract writes a hidden .checksums.md5 file recording the pristine "
         "assets. The Replace tabs and Write use it to tell what you have "
         "changed — leave it in place."),
        ("Re-extracting",
         "Extracting into a non-empty folder overwrites your edits (after a "
         "confirmation). Use a fresh output folder per firmware version."),
    ],
    "Replace Audio": [
        ("Scan and assign",
         "Scan lists every sound slot in the assets folder. Assign a "
         "replacement per slot — almost any audio format is accepted (mp3, "
         "wav, ogg, flac, m4a, …); it doesn't need to match the original, "
         "it's converted and fitted (length / sample rate / volume) "
         "automatically when you build."),
        ("Assets folder + applying",
         "The assets folder is the one Extract produced — the same folder the "
         "Write tab reads. There's no separate \"stage\" step: the "
         "replacements you assign are applied automatically when you build the "
         "update on the Write tab."),
        ("Change markers",
         "Green = assigned this session (staged when you build). "
         "\"✓ changed on disk\" = the file already differs from the extract "
         "baseline (an earlier build or a hand edit). The counter shows every "
         "change the next build will pack — not just this session's."),
        ("Preview",
         "Two players side by side — the original on the left, your "
         "replacement on the right — each with its own controls, so you can "
         "compare them before you commit to a build. Starting one pauses "
         "the other."),
        ("Undo",
         "Right-click a slot: \"Remove replacement\" cancels an un-built "
         "assignment; \"Revert to original\" restores an already-changed "
         "file. \"Revert all changes…\" on the Write tab resets everything."),
        ("Finding things",
         "Click any column header to sort (click again to flip). The search "
         "box filters by name — with auto-naming on, that includes the "
         "transcribed call-out text and matched song titles."),
    ],
    "Replace Video": [
        ("Scan and assign",
         "Scan lists every video slot; assign a replacement clip per slot "
         "and compare it against the original in the side-by-side preview "
         "players before building. A clip that already matches the "
         "original's format, resolution and frame rate is used as-is; "
         "anything else is auto-re-encoded to match (transparency is kept "
         "where the original has it)."),
        ("Assets folder + applying",
         "The assets folder is the one Extract produced — the same folder the "
         "Write tab reads. There's no separate \"stage\" step: the "
         "replacements you assign are applied automatically when you build the "
         "update on the Write tab."),
        ("Size limits",
         "Patching is size-neutral: a same-or-smaller replacement fits "
         "as-is, a larger one is re-encoded down to the slot's byte budget. "
         "A replacement that already matches the slot's format is copied "
         "through verbatim — no quality loss."),
        ("No conversion",
         "Where shown, the \"No conversion\" option forces a verbatim copy "
         "of a same-container file and skips all re-encoding."),
        ("Undo",
         "Right-click a slot to remove an un-built assignment or revert an "
         "already-changed file."),
    ],
    "Replace Images": [
        ("Scan and assign",
         "Scan lists the game's replaceable images. Assign a replacement "
         "per slot — almost any image format works; it is auto-scaled to "
         "the original's pixel dimensions and converted to the slot's "
         "format (transparency is kept where the original has it). Keep "
         "the original resolution for best results."),
        ("Assets folder + applying",
         "The assets folder is the one Extract produced — the same folder the "
         "Write tab reads. There's no separate \"stage\" step: each "
         "replacement you assign is auto-fit to its slot (scaled, "
         "format-converted, size-matched) and applied automatically when you "
         "build the update on the Write tab."),
        ("Where images come from",
         "The Source column tells the four stores apart. \"File\" = a "
         "plain image file on the card (menus, apron/test art). \"Scene "
         "texture\" = artwork decoded out of the game's compiled display "
         "scenes — many are frames of an animation or sprite sheets. "
         "\"Radium\" = images embedded inside the scene descriptions "
         "themselves (song-title banners and similar). \"Glyph\" = a single "
         "character sliced out of a font atlas (see Font atlases below). "
         "All four replace the same way; the Source dropdown in the toolbar "
         "narrows the list to one store, and clicking the Source header "
         "sorts by it."),
        ("Scene groups",
         "\"Group by scene\" nests each image under the scene / animation "
         "it belongs to, in play order. Right-click a group header to "
         "assign one replacement to every frame, blank the whole "
         "animation (transparent), clear its pending replacements, or "
         "rename the group — most factory scene names are generic "
         "(\"unnamed_instance_14\"); your name is remembered for that "
         "assets folder and is matched by Search."),
        ("Font atlases",
         "Some scene textures are font/glyph maps — a grid of characters "
         "the game draws text from. You can re-style the whole grid, but "
         "keep every glyph in its original position: the game blits fixed "
         "rectangles, so moving or resizing glyphs scrambles on-screen text."),
        ("Editing one letter (Glyph source)",
         "To restyle a single character without touching the grid, set the "
         "Source dropdown to \"Glyph\": the app slices each font atlas into "
         "one image per character (named by its letter, e.g. \"U+0041 A\") "
         "and drops your replacement back into that character's exact "
         "rectangle — so you can redraw just the \"S\" and leave the rest "
         "alone. These sit under scene_textures/glyphs/ in the extract."),
        ("Size limits",
         "Patching is size-neutral: the encoded replacement must fit the "
         "original slot's byte budget — a small enough image drops "
         "straight in, a larger one is re-compressed (fewer colours) to "
         "fit, and one that still won't fit is skipped (left unchanged); "
         "use a simpler image. Exception: scene/radium glyph and sprite "
         "atlases are re-encoded losslessly to the slot's exact "
         "dimensions with no byte-size limit."),
        ("Undo",
         "Right-click a slot to remove an un-built assignment or revert an "
         "already-changed file."),
    ],
    "Replace Text": [
        ("Scan and edit",
         "Scan loads the game's editable display strings from the assets "
         "folder Extract produced — the same folder the Write tab reads. Pick "
         "a row and type the new text in the edit panel — the original is "
         "always kept alongside for reference. Edits are saved straight into "
         "the manifest and patched in on the next Write."),
        ("Length limits",
         "Replacements live in the original string's slot: same-length or "
         "shorter is padded automatically; over-long text is rejected."),
        ("Apply to all",
         "\"Apply to every scene with the same original text\" repeats the "
         "edit everywhere that exact original string occurs (many strings "
         "repeat once per scene/keyframe)."),
    ],
    "Write": [
        ("What a build does",
         "Build copies the pristine original and repacks every file in the "
         "assets folder that differs from the extract baseline — including "
         "changes from earlier sessions, not just today's. Changed sounds "
         "are re-encoded and replaced videos / images / text are patched in "
         "size-neutrally, so the built file is a drop-in replacement for "
         "the original. The Modified Files list previews exactly what will "
         "go in before you click."),
        ("Output name",
         "Built images get a distinct default name (e.g. \"…-modified.raw\", "
         "where supported) so they can't be mistaken for the stock file. "
         "Typing a full filename into Output Folder overrides it."),
        ("Undo",
         "\"Revert all changes…\" restores every changed asset back to its "
         "extract original (the build inputs, not any card)."),
        ("Direct write",
         "\"Write to SD card / SSD\" (where available) applies the same "
         "changes straight to the physical media. Remove the media from the "
         "machine first and always keep a backup image."),
        ("Flash image",
         "\"Flash image to SD card…\" (where available, beside Build) "
         "writes a complete pre-built image onto a card — for putting the "
         "image you just built onto the card, or restoring a backup, "
         "without a separate imaging tool. The whole card is erased and "
         "replaced; a size check refuses an image too big for the card. "
         "The dialog pre-fills with the image the Output Folder + File "
         "Name boxes point at once it exists. Requires Administrator."),
    ],
    "Mod Pack": [
        ("Export",
         "Export bundles everything you've changed (versus the extract "
         "baseline) into a single shareable mod-pack file."),
        ("Import",
         "Import applies a mod pack onto a matching extract — the pack "
         "records which game/version it was made from."),
        ("Transfer mods",
         "\"Transfer mods from another extract\" (where available) carries "
         "your Replace edits from an older firmware's extract onto a new "
         "version's extract. Audio is matched by content signature, so it "
         "survives renumbered slots and renamed files; anything that can't "
         "be matched is reported instead of silently dropped."),
    ],
    "Partition Explorer": [
        ("What it's for",
         "Browse a raw card image (.raw / .img) the way a file manager would — "
         "read-only. Handy for pulling a file (a radium scene, a boot script) "
         "out of an old modded card to reuse, or dumping a folder to compare a "
         "modded card against a stock one. Nothing on the card is ever "
         "changed."),
        ("Open a card",
         "Point \"Card Image\" at a card image and press Open. The app reads "
         "the disk's partitions and picks the first browsable Linux (ext4) one; "
         "switch partitions with the dropdown. FAT and extended partitions are "
         "listed but not browsable."),
        ("Browse + preview",
         "Expand folders in the tree to walk the filesystem — children load as "
         "you open each folder, so even a full card opens instantly. Selecting "
         "a small text file shows it in the Preview pane; larger or binary "
         "files say to extract them instead."),
        ("Extract",
         "\"Extract Selected\" saves the highlighted file, or the highlighted "
         "folder's whole subtree, to a location you pick. \"Extract Whole "
         "Partition\" dumps the entire filesystem — useful for diffing two "
         "cards."),
    ],
}

# Appended to every tab's sections — app-wide behaviours users ask about.
GENERAL_CONTENT = [
    ("The ⚙ settings menu",
     "The gear in the top-right collects the app-wide controls: light/dark "
     "theme, update check, disk-space management, voice recognition "
     "quality, and the prerequisite tools (status, re-check, install)."),
    ("Prerequisites",
     "Each manufacturer needs a few tools installed. While anything is "
     "still being checked or missing, a strip under the title lists them: "
     "[?] = still checking, [✗] = missing (\"Install Missing\" sets them "
     "up), [✓] = ready. Once everything is ready the strip tucks itself "
     "away — the ⚙ menu keeps the status."),
    ("Recent paths",
     "Every file/folder box keeps a per-manufacturer history — open its "
     "dropdown to reuse a recent path."),
    ("The log",
     "The progress dots and log at the bottom mirror every operation; "
     "right-click the log to copy text for a bug report."),
]

_WIDTH, _HEIGHT = 560, 520


class TabHelpWindow:
    """The single per-app tips window.

    ``show(tab)`` opens it (or re-focuses + re-renders the open one);
    ``refresh(tab)`` re-renders in place without stealing focus/placement —
    used when the user switches notebook tabs or flips the theme with the
    window open.
    """

    def __init__(self, parent, theme_fn):
        self._parent = parent
        self._theme_fn = theme_fn        # () -> current theme name
        self._dlg = None
        self._text = None
        self._tab_name = None

    def is_open(self):
        try:
            return self._dlg is not None and bool(self._dlg.winfo_exists())
        except tk.TclError:
            return False

    def show(self, tab_name):
        """Open (or surface) the window rendered for *tab_name*."""
        if self.is_open():
            self._render(tab_name)
            self._dlg.deiconify()
            self._dlg.lift()
            self._dlg.focus_set()
            return self._dlg
        self._build()
        self._render(tab_name)
        return self._dlg

    def refresh(self, tab_name=None):
        """Re-render the open window (new tab and/or new theme).  Keeps the
        user's placement and stacking order; no-op when closed."""
        if self.is_open():
            self._render(tab_name or self._tab_name)

    def close(self):
        if self.is_open():
            self._dlg.destroy()
        self._dlg = None
        self._text = None

    # -- internals -----------------------------------------------------

    def _build(self):
        sans, _ = platform_font()
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        dlg.transient(self._parent.winfo_toplevel())
        dlg.minsize(420, 300)

        body = ttk.Frame(dlg, padding=(14, 10, 8, 10))
        body.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(
            body, wrap="word", relief=tk.FLAT, borderwidth=0,
            font=(sans, 10),
            padx=4, pady=2, cursor="arrow",
            highlightthickness=0)
        self._text = text
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 10))
        close = ttk.Button(btn_row, text="Close", command=self.close)
        close.pack(side=tk.RIGHT)

        dlg.bind("<Escape>", lambda _e: self.close())
        dlg.protocol("WM_DELETE_WINDOW", self.close)
        dlg.geometry(f"{_WIDTH}x{_HEIGHT}")
        # Centre over the parent window, clamped to the screen — first open
        # only; a refresh/re-show keeps wherever the user dragged it.
        dlg.update_idletasks()
        try:
            pw = self._parent.winfo_toplevel()
            x = pw.winfo_rootx() + (pw.winfo_width() - _WIDTH) // 2
            y = pw.winfo_rooty() + (pw.winfo_height() - _HEIGHT) // 2
            x = max(0, min(x, dlg.winfo_screenwidth() - _WIDTH))
            y = max(0, min(y, dlg.winfo_screenheight() - _HEIGHT))
            dlg.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        close.focus_set()

    def _render(self, tab_name):
        self._tab_name = tab_name
        sections = HELP_CONTENT.get(tab_name)
        if sections is None:
            # Unknown/renamed tab — show just the general tips rather than
            # nothing so the button never feels broken.
            sections = []
        th = THEMES.get(self._theme_fn()) or THEMES["light"]
        sans, _ = platform_font()

        dlg, text = self._dlg, self._text
        dlg.title(f"Tips — {tab_name}" if tab_name else "Tips")
        dlg.configure(bg=th["bg"])
        # (Re)apply theme colors every render so an open window follows a
        # light/dark switch instead of keeping the stale palette.
        text.configure(state=tk.NORMAL, bg=th["bg"], fg=th["fg"],
                       selectbackground=th["select_bg"])
        text.tag_configure("h", font=(sans, 10, "bold"),
                           spacing1=10, spacing3=2, foreground=th["fg"])
        text.tag_configure("body", spacing3=4,
                           lmargin1=14, lmargin2=14, foreground=th["fg"])
        text.tag_configure("rule", font=(sans, 10, "bold"),
                           spacing1=16, spacing3=2, foreground=th["gray"])

        text.delete("1.0", tk.END)
        for title, para in sections:
            text.insert(tk.END, title + "\n", "h")
            text.insert(tk.END, para + "\n", "body")
        text.insert(tk.END, "General\n", "rule")
        for title, para in GENERAL_CONTENT:
            text.insert(tk.END, title + "\n", "h")
            text.insert(tk.END, para + "\n", "body")
        text.configure(state=tk.DISABLED)


def show_tab_help(parent, tab_name, theme_name):
    """One-shot helper (tests/back-compat): open a fresh tips window for
    *tab_name* and return its Toplevel.  The app itself goes through a
    long-lived :class:`TabHelpWindow` so "?" re-uses one window."""
    win = TabHelpWindow(parent, lambda: theme_name)
    win.show(tab_name)
    return win._dlg
