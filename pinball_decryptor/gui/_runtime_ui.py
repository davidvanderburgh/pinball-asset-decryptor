"""Installing, repairing and REPLACING the app's own Linux, from a tab.

★ WHY THIS IS SHARED, and why it had to be before the version stamp in
core/runtime.py was ever bumped.

The runtime carries a version stamp and the app refuses to use one whose stamp
is not the number this build expects: :func:`core.runtime.wsl_distro` answers
None on a stale runtime, and every path into Linux then falls back to whatever
distro the machine calls default - which is exactly what a machine with no
runtime has always done.  That fallback is the right one.  Nothing is deleted
and nothing crashes.  But it is SILENT, and until this module existed the only
place in the whole app that could act on it was the Spike 1 Emulate tab:
``runtime.install`` had three call sites and all three were in that one file.

So the first stamp bump would have reached a Spike 2 user like this.  Update
the app; the emulator quietly leaves the Linux it had been working in for one
that carries none of its toolchain; the prerequisite rows go red; and the card
cache and the SAVE-STATE SLOTS are still sitting in the old distro, untouched,
but not where the rig now looks.  A re-copy that takes minutes and a rebuild of
the rig's binaries look, from the outside, exactly like losing them.  And the
cure was a button on a tab that user had no reason ever to open.

Hence one definition of the consent dialog, one definition of the ladder, and
any tab that can meet a stale runtime can offer the same fix in the same words.

NOTHING HERE DESTROYS ANYTHING WITHOUT BEING TOLD TO.  ``runtime.install``
raises :class:`~core.runtime.RuntimeNeedsReplacing` rather than replacing a
registered distro, and the only thing that turns that into a yes is ``ask``,
which is a human in front of a dialog that names the save states by name.
"""
import sys
from tkinter import filedialog, messagebox

from ..core import runtime

#: The states where there is nothing for a user to do and nothing to say: this
#: machine cannot have a runtime, or this build has not pinned an image yet.
#: Not faults - the feature does not apply here.
QUIET = ("unsupported", "unpublished")

#: The states :func:`ensure` can act on.  ``foreign`` is deliberately NOT in
#: it: a distro of our name that is not ours is somebody else's, and the app
#: says so and stops rather than offering to delete it.
FIXABLE = ("absent", "stale")

#: ...and the much narrower set a TAB volunteers a notice about, which is one
#: state: the runtime went out of date under a user who had one.
#:
#: NOT ``absent``, deliberately, and this is the difference between telling
#: someone something changed and nagging them.  A Windows machine that never
#: had the runtime is not broken - it is how every Spike 2 user has run since
#: before the runtime existed, in the machine's own distro, and a permanent
#: orange banner offering a 414 MB download to a setup that works is noise.  A
#: machine that is genuinely missing tools already hears about it from the
#: prerequisite notice, which is the right channel for that and says which
#: tools.  ``stale`` is different in kind: nothing about that machine changed,
#: WE changed, and the emulator moved out from under them.
UNPROMPTED = ("stale",)


def ask_before_replacing(parent=None) -> bool:
    """Name what is about to be destroyed, then let a human decide.

    ONE WORDING, because two would drift and this is the sentence that stands
    between a user and a save state they cannot get back.
    """
    return messagebox.askyesno(
        "Replace the emulator's Linux?",
        "This app installs its own Linux (%s), and one is already "
        "installed here from an older version.\n\n"
        "Replacing it DELETES everything inside it:\n"
        "  - games extracted from your cards (about a minute each to redo)\n"
        "  - cached cards\n"
        "  - any SAVE STATES you made while running in it\n\n"
        "Nothing outside it is touched: your cards, your extractions on "
        "this PC and your own WSL distro all stay as they are.\n\n"
        "Replace it now?" % runtime.DISTRO, parent=parent)


def notice(state, detail) -> str:
    """The sentence a tab puts on itself when the runtime needs attention.

    It has to answer the question the user is actually holding, which is not
    "what is a runtime" but "where did my emulator go".  So it says what the
    app is doing INSTEAD (using the machine's own distro), that nothing has
    been lost, and which button fixes it.
    """
    if state == "stale":
        return ("The emulator's Linux is from an older version of this app, "
                "so the emulator is running in this PC's own WSL distro "
                "instead - which does not carry the emulator's toolchain, so "
                "things here may not work until it is updated.\n"
                "Nothing has been lost: your cards, extractions and save "
                "states are still in the old one. Press “Update emulator "
                "Linux…” to move to the current one.")
    if state == "absent":
        return ("The Linux this app installs for the emulator is not here "
                "yet, so the emulator is using this PC's own WSL distro. "
                "Press “Update emulator Linux…” to install it "
                "(a one-time download).")
    if state == "foreign":
        # NOT OFFERED AS A FIX, and this is the message that says why: a
        # distro of that name the app did not build is somebody else's, and
        # deleting it is not the app's call to make.
        return ("A WSL distro called %s exists here but is not the one this "
                "app builds, so the app will not touch it. The emulator is "
                "using this PC's own WSL distro instead. Rename or remove "
                "that distro if you want the app to install its own."
                % runtime.DISTRO)
    return ""


def ensure(say, progress=None, ask=None, on_blocked=None):
    """status -> install -> (consent) -> replace.  Returns the state after.

    *say* takes one already-prefixed line.  *ask* is the consent gate and
    defaults to :func:`ask_before_replacing`; a caller passes its own so a
    test can answer it.  *on_blocked* gets the :class:`RuntimeError` from a
    download that could not happen, which is where the from-a-file route is
    offered.

    ``None`` means "this machine is not one that has a runtime" - not a
    failure, and a caller should say nothing at all about it.
    """
    ask = ask or ask_before_replacing
    state, detail = runtime.status(refresh=True)
    if state in QUIET:
        return None
    if state in ("ready", "foreign"):
        say(detail)
        return state
    say("installing the Linux the emulator runs on (%s)…"
        % runtime.IMAGE.version)
    try:
        runtime.install(log=say, progress=progress)
    # THE SPECIFIC ONE FIRST.  RuntimeNeedsReplacing IS a RuntimeError, so
    # with the broad handler below written above it the narrow one never runs,
    # and the consent dialog this whole path exists for is unreachable - the
    # user just sees the refusal in the log.  That is not hypothetical: it is
    # how this shipped the first time, in the Spike 1 tab.
    except runtime.RuntimeNeedsReplacing:
        if not ask():
            say("left the installed runtime alone.")
            return state
        runtime.install(log=say, progress=progress, replace=True)
    except RuntimeError as exc:
        # A blocked download, a proxy, an antivirus: the image has an offline
        # route too, and this is where it is offered.
        say(str(exc))
        if on_blocked is not None:
            on_blocked(exc)
        return state
    return "ready"


def offer_from_file(say, exc, ask=None, parent=None):
    """The blocked-download path for the IMAGE, not just the small binaries.

    370 MB from a host some proxies refuse is the download most likely to be
    stopped, and it was the one with no way round.  Same checksum, different
    delivery - so this is a different route, not a lower standard.
    """
    ask = ask or (lambda: ask_before_replacing(parent))
    if not messagebox.askyesno(
            "Install the runtime from a file",
            "%s\n\nIf you can copy %s onto this machine another way, choose "
            "it now - it is checked against the same checksum before "
            "anything is installed.\n\nChoose a file?"
            % (exc, runtime.IMAGE.filename), parent=parent):
        return
    path = filedialog.askopenfilename(
        title="Choose the downloaded %s" % runtime.IMAGE.filename,
        initialfile=runtime.IMAGE.filename)
    if not path:
        return
    try:
        runtime.install(log=say, source=path,
                        replace=(ask()
                                 if runtime.status()[0] != "absent" else False))
    except Exception as e:                                 # noqa: BLE001
        say(str(e))


def can_install() -> bool:
    """Is installing something this platform can even do?

    Windows only, like the runtime itself.  A Mac reaching the offer would be
    offered a WSL distro it has nowhere to put.
    """
    return sys.platform == "win32"
