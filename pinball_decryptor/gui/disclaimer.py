"""First-launch disclaimer dialog.

Shown once when the user has never accepted the terms.  Acceptance is
persisted in ``settings.json`` as a simple boolean (``disclaimer_accepted``)
and survives across app updates — the flag is intentionally NOT
versioned, so reinstalls and version bumps do not re-prompt.

The user must click "I Agree" to proceed; declining or closing the
dialog returns False so the caller can exit cleanly.
"""

import tkinter as tk

from .theme import THEMES, platform_font


DISCLAIMER_TITLE = "Important — Read Before Use"

DISCLAIMER_HEADER = "Please read carefully before using this tool"

# Bulleted body — assembled paragraph-style in the Text widget so wrap
# behaves nicely on resize.  Bullets are pre-wrapped with hanging indent
# via Text's tab-stops.
DISCLAIMER_BODY = (
    "Pinball Asset Decryptor lets you extract, modify, and repack the "
    "firmware files used by commercial pinball machines.\n"
    "\n"
    "If you install modified firmware on a physical machine, please "
    "understand:\n"
    "\n"
    "  •  Doing so WILL LIKELY VOID YOUR WARRANTY.  Manufacturers are "
    "under no obligation to honor warranty claims on machines running "
    "unsigned, third-party, or user-modified code.\n"
    "\n"
    "  •  Modifications can break gameplay, audio, video, scoring, or "
    "hardware control in subtle ways.  Some failures may only appear "
    "hours or days after install.\n"
    "\n"
    "  •  ALWAYS MAKE A COMPLETE, WORKING BACKUP before modifying a "
    "machine.  A failed, interrupted, or incorrect update can leave the "
    "machine unbootable (\"bricked\"); without a known-good backup image "
    "you may be unable to recover it.  This app is not responsible for "
    "bricked machines.\n"
    "\n"
    "  •  DO NOT contact the manufacturer's support team about issues "
    "that may have been caused — directly or indirectly — by modified "
    "code.  Revert to stock firmware before opening a support ticket, "
    "and disclose any past modifications.  Support resources exist for "
    "real defects, not for self-inflicted ones; creating noise in that "
    "queue makes the experience worse for every other owner.\n"
    "\n"
    "  •  This tool is provided \"as-is\" with no warranty of any kind. "
    " The authors and contributors accept no liability for damage to "
    "your machine, lost data, voided warranties, or other consequences "
    "of use.\n"
    "\n"
    "By clicking \"I Agree\" you acknowledge that you understand these "
    "risks, that you take full responsibility for any modifications you "
    "install on a physical machine, and that you will not create "
    "support burden for the manufacturer based on issues caused by "
    "user modifications."
)


def show_disclaimer_dialog(parent, theme_name="light"):
    """Show a blocking modal disclaimer dialog.

    Returns True if the user clicked "I Agree".  Returns False if they
    clicked "Quit" or closed the window — caller should exit.
    """
    theme = THEMES.get(theme_name) or THEMES["light"]
    sans_font, _ = platform_font()

    dlg = tk.Toplevel(parent)
    dlg.title(DISCLAIMER_TITLE)
    dlg.configure(bg=theme["bg"])
    dlg.transient(parent)
    dlg.resizable(False, False)

    accepted = {"value": False}

    container = tk.Frame(dlg, bg=theme["bg"], padx=22, pady=18)
    container.pack(fill="both", expand=True)

    tk.Label(
        container, text=DISCLAIMER_HEADER,
        font=(sans_font, 13, "bold"),
        bg=theme["bg"], fg=theme["fg"], anchor="w",
    ).pack(fill="x", pady=(0, 12))

    # Text widget so the body can wrap on its own; disabled state
    # prevents the cursor from showing or the user from editing it.
    # Size the body to fit the wrapped text — the disclaimer is ~24
    # wrapped lines at width=72, so height=28 leaves a small breathing
    # margin without forcing a scrollbar.  If we ever grow the text,
    # bump this rather than relying on a scrollbar that hides content.
    body = tk.Text(
        container, wrap="word", width=72, height=28,
        bg=theme["field_bg"], fg=theme["fg"],
        font=(sans_font, 10),
        relief="flat", padx=14, pady=12,
        borderwidth=1, highlightthickness=1,
        highlightbackground=theme["border"],
        highlightcolor=theme["border"],
    )
    body.insert("1.0", DISCLAIMER_BODY)
    body.configure(state="disabled")
    body.pack(fill="both", expand=True, pady=(0, 14))

    btn_row = tk.Frame(container, bg=theme["bg"])
    btn_row.pack(fill="x")

    def _accept():
        accepted["value"] = True
        dlg.destroy()

    def _decline():
        accepted["value"] = False
        dlg.destroy()

    # macOS renders tk.Button with a native (light) Aqua face and ignores
    # ``bg``, so a dark-theme button with light ``fg`` text was unreadable
    # there (light text on a light face).  Build the buttons from tk.Label
    # instead -- Labels honor bg/fg on every platform (the same faux-button
    # pattern the manufacturer picker uses) -- with a click binding and a
    # hover swap for affordance.
    def _make_button(text, command, *, bg, fg, hover_bg, bold=False):
        lbl = tk.Label(
            btn_row, text=text, bg=bg, fg=fg,
            font=(sans_font, 10, "bold" if bold else "normal"),
            padx=20 if bold else 18, pady=7, cursor="hand2",
        )
        lbl.bind("<Button-1>", lambda _e: command())
        lbl.bind("<Enter>", lambda _e: lbl.configure(bg=hover_bg))
        lbl.bind("<Leave>", lambda _e: lbl.configure(bg=bg))
        return lbl

    # Quit on the right, primary action ("I Agree") to its right so it's
    # the rightmost button — matches the OK-on-right Windows/Linux convention.
    _make_button(
        "Quit", _decline,
        bg=theme["button"], fg=theme["fg"], hover_bg=theme["border"],
    ).pack(side="right", padx=(8, 0))

    accept_btn = _make_button(
        "I Agree", _accept,
        bg=theme["accent"], fg="#ffffff", hover_bg=theme["select_bg"],
        bold=True,
    )
    accept_btn.pack(side="right")

    # Keyboard: Enter accepts, Esc declines.  tk.Label doesn't inherit the
    # focused-button Return behavior tk.Button had, so bind it on the dialog.
    dlg.bind("<Return>", lambda _e: _accept())
    dlg.bind("<Escape>", lambda _e: _decline())

    # Closing the X = decline.
    dlg.protocol("WM_DELETE_WINDOW", _decline)

    # Center over the parent (or screen if parent isn't mapped yet).
    parent.update_idletasks()
    dlg.update_idletasks()
    dw = max(dlg.winfo_reqwidth(), 640)
    dh = max(dlg.winfo_reqheight(), 540)
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    if pw <= 1 or ph <= 1:
        # Parent not mapped yet — center on the screen instead.
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        x = (sw - dw) // 2
        y = (sh - dh) // 2
    else:
        x = parent.winfo_rootx() + (pw - dw) // 2
        y = parent.winfo_rooty() + (ph - dh) // 2
    dlg.geometry(f"{dw}x{dh}+{max(0, x)}+{max(0, y)}")

    # Modal: lift above the parent, ensure mapping has happened, then
    # grab focus.  On Windows pythonw a grab_set call against a
    # not-yet-mapped Toplevel silently fails and the dialog destroys
    # itself immediately — explicit lift + update_idletasks avoids that
    # race.
    dlg.deiconify()
    dlg.lift()
    dlg.update_idletasks()
    try:
        dlg.grab_set()
    except tk.TclError:
        # Grab can fail if the window isn't viewable yet; one more
        # update + retry usually resolves it.
        dlg.update()
        dlg.grab_set()
    accept_btn.focus_set()
    parent.wait_window(dlg)

    return accepted["value"]
