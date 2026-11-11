"""PyInstaller entry point — uses absolute imports instead of relative.

PyInstaller's frozen apps run as `__main__`, not as a package, so the
package-relative imports inside ``pinball_decryptor/__main__.py`` would
fail.  This shim launches the app with the proper absolute import path.
"""

import multiprocessing
import sys


if __name__ == "__main__":
    # Linux: the system's programs (ffmpeg above all) get the system's
    # libraries, not the bundle's older ones (PAD-837).  Before
    # freeze_support, which runs a multiprocessing worker and exits there:
    # workers start system programs too (PAD-875).
    from pinball_decryptor.core.desktop import guard_child_env
    guard_child_env()

    # Required so PyInstaller-frozen child processes spawned by multiprocessing
    # (Stern Spike 2 parallel audio decode) bootstrap instead of re-running the
    # app.  Must come before any app code runs.
    multiprocessing.freeze_support()

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

    # The Mac emulator's sound cushion (PAD-1109): the frozen binary with
    # --pace runs tools/spike2_emu/padrelay.py's pacer between docker exec and
    # ffplay, so the speaker is never starved by a lumpy transport. The app's
    # own Python, because a Mac has no other for certain; nothing of the GUI
    # is imported for it.
    if "--pace" in sys.argv:
        import importlib.util
        import os
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        relay = os.path.join(base, "tools", "spike2_emu", "padrelay.py")
        spec = importlib.util.spec_from_file_location("padrelay", relay)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.exit(mod.pace_main(sys.argv[sys.argv.index("--pace") + 1:]))

    from pinball_decryptor.webui.host import main
    sys.exit(main(sys.argv[1:]))
