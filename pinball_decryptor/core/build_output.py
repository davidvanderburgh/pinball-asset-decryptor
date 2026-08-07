"""Make sure a Build's destination folder exists before the write starts.

Nothing in the Build flow created it.  The Write tab checks that the original
is a file and that the assets folder is a directory, then hands an output path
straight to the plugin's write pipeline, whose first act is to copy the card
image there — so a Build Location that isn't on disk yet (a fresh project's
``build`` subfolder, or one "Delete build" removed, or a destination the user
just re-pointed) died with a bare

    [Errno 2] No such file or directory: '…\\build\\<card>-modified.raw'

That names the FILE, not the missing folder, so it reads as "the app can't
find my card image".  A tester (batch 30) drew exactly the opposite conclusion
from the truth: "it's complaining there is no file or directory — the
directory does exist, so it must not have the file."

Two details made it worse, and both are why this runs up front rather than
being left to a nicer error message:

  * Stern's engine copies the image on a background thread while it computes
    the edits and only re-raises the copy's failure at the join, so the box
    appeared ~90 seconds in, under a wall of unrelated log lines.
  * With machine-render previews on, the encoder creates its previews folder
    *inside* that same build folder while the compute runs — so by the time
    the error appeared, the folder it had failed on genuinely existed.
"""

import os

from . import longpath


def ensure_dir_for(output_path):
    """Create the folder *output_path* will be written into.

    Returns ``""`` when the folder is there (or was just made), else one human
    sentence-block saying why it isn't.  Callers report that and stop: an
    unwritable destination is the user's to fix, and finding out before the
    re-encode beats finding out after it.
    """
    if not output_path:
        return "No build destination was given."
    d = os.path.dirname(os.path.abspath(str(output_path)))
    if not d:
        return ""
    lp = longpath.ext(d)
    if os.path.isdir(lp):
        return ""
    if os.path.exists(lp):
        return ("The build's destination\n\n    %s\n\nis a file, not a folder. "
                "Pick a different Build Location." % d)
    try:
        os.makedirs(lp, exist_ok=True)
    except OSError as e:
        hint = longpath.hint(d)
        return ("Could not create the build's destination folder\n\n    %s\n\n"
                "%s%s" % (d, e.strerror or e, ("\n\n" + hint) if hint else ""))
    return ""
