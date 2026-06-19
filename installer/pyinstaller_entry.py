"""PyInstaller entry point — uses absolute imports instead of relative.

PyInstaller's frozen apps run as `__main__`, not as a package, so the
package-relative imports inside ``pinball_decryptor/__main__.py`` would
fail.  This shim launches the app with the proper absolute import path.
"""

import multiprocessing

from pinball_decryptor.app import App


if __name__ == "__main__":
    # Required so PyInstaller-frozen child processes spawned by multiprocessing
    # (Stern Spike 2 parallel audio decode) bootstrap instead of re-running the
    # app.  Must be the first thing the frozen entry does.
    multiprocessing.freeze_support()
    App().run()
