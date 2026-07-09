"""Entry point: python -m pinball_decryptor"""

import sys

if __name__ == "__main__":
    # Elevated flash-helper re-invocation (see core.elevated_flash): runs the
    # raw card write as Administrator/root without a GUI, then exits.  Must be
    # handled before importing the Tk app.
    if "--flash-helper" in sys.argv:
        from .core.elevated_flash import run_helper_main
        sys.exit(run_helper_main(sys.argv))

    from .app import App
    App().run()
