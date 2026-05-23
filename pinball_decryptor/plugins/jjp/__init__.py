"""Jersey Jack Pinball plugin entry point."""

# The plugin code is no longer tracked separately — every change
# ships from this unified repo, so any "plugin version" we report
# would just be the unified app's version with extra steps.  The
# old ``__version__`` lived here when the code was lifted verbatim
# from the standalone jjp-decryptor; removing it now keeps the
# single source of truth at pinball_decryptor.__version__.

from ...core.registry import register_manufacturer
from .manufacturer import JJPManufacturer


def register():
    register_manufacturer(JJPManufacturer())
