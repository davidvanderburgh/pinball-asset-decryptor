"""PyInstaller entry point — uses absolute imports instead of relative.

PyInstaller's frozen apps run as `__main__`, not as a package, so the
package-relative imports inside ``pinball_decryptor/__main__.py`` would
fail.  This shim launches the app with the proper absolute import path.
"""

import multiprocessing
import sys


if __name__ == "__main__":
    # Required so PyInstaller-frozen child processes spawned by multiprocessing
    # (Stern Spike 2 parallel audio decode) bootstrap instead of re-running the
    # app.  Must be the first thing the frozen entry does.
    multiprocessing.freeze_support()

    # Linux: the system's programs (ffmpeg above all) get the system's
    # libraries, not the bundle's older ones (PAD-837).
    from pinball_decryptor.core.desktop import guard_child_env
    guard_child_env()

    # Elevated flash-helper re-invocation (see core.elevated_flash): the frozen
    # binary re-execs itself as root to run the raw card write, with no GUI.
    if "--flash-helper" in sys.argv:
        from pinball_decryptor.core.elevated_flash import run_helper_main
        sys.exit(run_helper_main(sys.argv))

    # The MCP server an AI agent starts (PAD-844): the frozen binary with
    # --mcp, as ``python -m pinball_decryptor.mcp`` is on Windows.
    if "--mcp" in sys.argv:
        from pinball_decryptor.mcp import main as mcp_main
        sys.exit(mcp_main())

    from pinball_decryptor.webui.host import main
    sys.exit(main(sys.argv[1:]))
