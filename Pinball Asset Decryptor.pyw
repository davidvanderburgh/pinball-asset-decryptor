"""Double-click launcher (no console window)."""

import multiprocessing
import os
import sys

# Guarded so worker processes spawned via multiprocessing (the Stern Spike 2
# parallel audio decode) re-import this module without re-launching the GUI.
if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # Dev-only: when /next item worktrees exist, offer to run one of them
    # instead of this checkout (no-op everywhere else — see worktree_picker).
    from pinball_decryptor.worktree_picker import dev_pick_checkout
    if dev_pick_checkout():
        # The web UI is the app; PAD_UI=tk starts the old Tk window until the
        # cut-over release removes it.
        if os.environ.get("PAD_UI", "").lower() == "tk":
            from pinball_decryptor.app import App
            App().run()
        else:
            from pinball_decryptor.webui.host import main
            sys.exit(main(sys.argv[1:]))
