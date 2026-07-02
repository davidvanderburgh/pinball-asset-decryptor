"""Per-tab tips modal — the header "?" button (monkeybug feedback).

Every working-view tab carries a pile of behaviour that used to live only in
inline grey prose or hover tooltips.  This modal collects those tips per tab
so a user can pull up "everything worth knowing about this page" on demand
instead of hunting for hidden hovers.

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
         "Pack tabs."),
        ("Auto-naming",
         "\"Auto-name call-outs\" transcribes speech locally (the first run "
         "downloads a ~75 MB model, after that it works offline). "
         "\"Auto-name music\" fingerprints full-length tracks against the "
         "online AcoustID database — the number after a matched title (e.g. "
         "0.97) is the match confidence. Results are also written to "
         "callouts.csv and music_titles.csv in the output folder."),
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
         "replacement per slot — most common audio formats are accepted and "
         "are converted and fitted (length / sample rate / volume) "
         "automatically when you build."),
        ("Change markers",
         "Green = assigned this session (staged when you build). "
         "\"✓ changed on disk\" = the file already differs from the extract "
         "baseline (an earlier build or a hand edit). The counter shows every "
         "change the next build will pack — not just this session's."),
        ("Preview",
         "The player previews a slot and A/Bs the original against your "
         "replacement before you commit to a build."),
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
         "and preview A/B before building."),
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
         "per slot — it is converted to the slot's format automatically. "
         "Keep the original resolution for best results."),
        ("Size limits",
         "Patching is size-neutral: the encoded replacement must fit the "
         "original slot's byte budget; over-budget images are compressed "
         "harder or rejected with a warning."),
        ("Undo",
         "Right-click a slot to remove an un-built assignment or revert an "
         "already-changed file."),
    ],
    "Replace Text": [
        ("Scan and edit",
         "Scan loads the game's editable display strings. Pick a row and "
         "type the new text in the edit panel — the original is always kept "
         "alongside for reference."),
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
         "changes from earlier sessions, not just today's. The Modified "
         "Files list previews exactly what will go in before you click."),
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
         "\"Flash image\" (where available) writes a complete pre-built "
         "image onto a card, erasing everything on it — for restoring a "
         "backup or writing a built image without a separate imaging tool. "
         "Requires Administrator."),
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
}

# Appended to every tab's sections — app-wide behaviours users ask about.
GENERAL_CONTENT = [
    ("Prerequisites strip",
     "The row under the title shows this manufacturer's required tools. "
     "[?] = still checking, [✗] = missing (\"Install Missing\" sets them "
     "up), [✓] = ready."),
    ("Recent paths",
     "Every file/folder box keeps a per-manufacturer history — open its "
     "dropdown to reuse a recent path."),
    ("The log",
     "The progress dots and log at the bottom mirror every operation; "
     "right-click the log to copy text for a bug report."),
]


def show_tab_help(parent, tab_name, theme_name):
    """Open the tips modal for *tab_name* (a notebook tab caption)."""
    sections = HELP_CONTENT.get(tab_name)
    if sections is None:
        # Unknown/renamed tab — show just the general tips rather than
        # nothing so the button never feels broken.
        sections = []
    th = THEMES.get(theme_name) or THEMES["light"]
    sans, _ = platform_font()

    dlg = tk.Toplevel(parent)
    dlg.title(f"Tips — {tab_name}" if tab_name else "Tips")
    dlg.configure(bg=th["bg"])
    dlg.transient(parent.winfo_toplevel())
    dlg.minsize(420, 300)

    body = ttk.Frame(dlg, padding=(14, 10, 8, 10))
    body.pack(fill=tk.BOTH, expand=True)

    text = tk.Text(
        body, wrap="word", relief=tk.FLAT, borderwidth=0,
        bg=th["bg"], fg=th["fg"], font=(sans, 10),
        padx=4, pady=2, cursor="arrow",
        selectbackground=th["select_bg"],
        highlightthickness=0)
    scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    text.tag_configure("h", font=(sans, 10, "bold"),
                       spacing1=10, spacing3=2)
    text.tag_configure("body", spacing3=4,
                       lmargin1=14, lmargin2=14, foreground=th["fg"])
    text.tag_configure("rule", font=(sans, 10, "bold"),
                       spacing1=16, spacing3=2, foreground=th["gray"])

    for title, para in sections:
        text.insert(tk.END, title + "\n", "h")
        text.insert(tk.END, para + "\n", "body")
    text.insert(tk.END, "General\n", "rule")
    for title, para in GENERAL_CONTENT:
        text.insert(tk.END, title + "\n", "h")
        text.insert(tk.END, para + "\n", "body")
    text.configure(state=tk.DISABLED)

    btn_row = ttk.Frame(dlg)
    btn_row.pack(fill=tk.X, padx=14, pady=(0, 10))
    close = ttk.Button(btn_row, text="Close", command=dlg.destroy)
    close.pack(side=tk.RIGHT)

    dlg.bind("<Escape>", lambda _e: dlg.destroy())
    dlg.geometry("560x520")
    # Centre over the parent window, clamped to the screen.
    dlg.update_idletasks()
    try:
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - 560) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - 520) // 2
        x = max(0, min(x, dlg.winfo_screenwidth() - 560))
        y = max(0, min(y, dlg.winfo_screenheight() - 520))
        dlg.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass
    close.focus_set()
    return dlg
