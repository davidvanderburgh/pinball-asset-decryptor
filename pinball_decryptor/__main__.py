"""Entry point: python -m pinball_decryptor"""

import sys

if __name__ == "__main__":
    # Elevated flash-helper re-invocation (see core.elevated_flash): runs the
    # raw card write as Administrator/root without a window, then exits.  Must
    # be handled before starting the app.
    if "--flash-helper" in sys.argv:
        from .core.elevated_flash import run_helper_main
        sys.exit(run_helper_main(sys.argv))
    # PAD-1458: started hidden by the app's close; gives the space freed
    # inside its WSL disks back to Windows once the app is gone.
    if "--disk-giveback" in sys.argv:
        from .core.disk_giveback import helper_main
        sys.exit(helper_main(sys.argv))

    # PAD-1522: Explorer's right-click > Compact with PAD on a card image.
    # A small window of its own; the app is not started.
    if len(sys.argv) > 1 and sys.argv[1] == "--compact":
        from .webui.compact_window import main as _compact
        sys.exit(_compact(sys.argv[2:]))
    # PAD-1535: > Move with PAD, the card moved and kept compact.
    if len(sys.argv) > 1 and sys.argv[1] == "--move":
        from .webui.compact_window import main_move
        sys.exit(main_move(sys.argv[2:]))

    # Dev-only: when /next item worktrees exist, offer to run one of them
    # instead of this checkout (no-op everywhere else — see worktree_picker).
    from .worktree_picker import dev_pick_checkout
    if dev_pick_checkout():
        from .webui.host import main
        sys.exit(main(sys.argv[1:]))
