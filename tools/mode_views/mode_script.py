"""PAD-614: the Script tab's reader and writer moved into the app (pinball_decryptor.plugins.stern.mode_script); this
name keeps the PAD-611 mockups and tests working."""
import sys

from pinball_decryptor.plugins.stern import mode_script as _real

sys.modules[__name__] = _real
