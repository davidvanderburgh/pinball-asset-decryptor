"""Entry point: python -m pinball_decryptor"""

import sys

if __name__ == "__main__":
    # Elevated flash-helper re-invocation (see core.elevated_flash): runs the
    # raw card write as Administrator/root without a window, then exits.  Must
    # be handled before starting the app.
    if "--flash-helper" in sys.argv:
        from .core.elevated_flash import run_helper_main
        sys.exit(run_helper_main(sys.argv))

    # Dev-only: when /next item worktrees exist, offer to run one of them
    # instead of this checkout (no-op everywhere else — see worktree_picker).
    from .worktree_picker import dev_pick_checkout
    if dev_pick_checkout():
        from .webui.host import main
        sys.exit(main(sys.argv[1:]))
