"""WSL command execution — backward-compatibility wrapper.

All functionality has moved to executor.py. This module re-exports the
WSL-specific classes and the legacy win_to_wsl() helper so that existing
imports continue to work.
"""

from .executor import (  # noqa: F401
    CommandError as WslError,
    WslExecutor,
    find_usbipd,
)


def win_to_wsl(path):
    """Convert a Windows path to a WSL path.

    e.g. C:\\Users\\david\\file.img -> /mnt/c/Users/david/file.img

    Prefer executor.to_exec_path() for new code.
    """
    path = path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ":":
        drive = path[0].lower()
        return f"/mnt/{drive}{path[2:]}"
    return path
