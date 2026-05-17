"""Manufacturer plugin registry.

Each plugin module under :mod:`pinball_decryptor.plugins` defines a
:class:`Manufacturer` subclass and calls :func:`register_manufacturer` at
import time.  :func:`load_plugins` imports every known plugin so its
``register()`` runs.
"""

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .config import EXTRACT_PHASES, WRITE_PHASES
from .prereqs import Prerequisite  # re-exported for plugins

# Plugins are imported in this order at startup.  Order drives the
# dropdown ordering; auto-detect tries them in this sequence too.
_PLUGIN_MODULES = [
    "pinball_decryptor.plugins.pb",
    "pinball_decryptor.plugins.spooky",
    "pinball_decryptor.plugins.bof",
    "pinball_decryptor.plugins.jjp",
]


# ---------------------------------------------------------------------------
# Data classes describing what a plugin exposes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Game:
    key: str               # "alien", "halloween", ...
    display: str           # "Alien", "Halloween", ...
    manufacturer_key: str  # "pb", "spooky", ...
    notes: str = ""        # optional UI-visible hint shown in detect badge
    # Whether decryption/extraction is currently possible at all.
    # Set False for games whose encryption key isn't known or whose
    # format isn't (yet) implemented — picker shows them greyed out
    # with a tooltip explaining the reason.
    supported: bool = True
    unsupported_reason: str = ""


@dataclass(frozen=True)
class Capabilities:
    """Which tabs / actions the GUI should expose for this manufacturer."""
    extract: bool = True
    write: bool = False
    modpack: bool = False
    apply_delta: bool = False
    iso: bool = False


@dataclass(frozen=True)
class InputSpec:
    """File-dialog filter for the Extract tab's input picker."""
    label: str                              # "PB game files"
    extensions: Sequence[str] = field(default_factory=tuple)  # (".upd", ".iso")


# ---------------------------------------------------------------------------
# Manufacturer base class
# ---------------------------------------------------------------------------

class Manufacturer(ABC):
    """Base class for a manufacturer plugin.

    Subclasses must set class attributes ``key``, ``display``, ``games``,
    ``capabilities``, ``input_spec``, and implement :meth:`detect` plus the
    pipeline factories appropriate for their capabilities.
    """

    key: str = ""
    display: str = ""
    games: Sequence[Game] = ()
    capabilities: Capabilities = Capabilities()
    input_spec: InputSpec = InputSpec(label="Files", extensions=("*",))

    # Phase labels rendered in the GUI's phase indicator.  Each pipeline
    # produced by this manufacturer should call ``phase_cb(i)`` for
    # ``0 <= i < len(phases)``.  Override per manufacturer when the
    # default 4-step shape doesn't match — e.g. BOF's Decrypt has 5
    # phases (Detect/Decrypt/Extract/Checksums/Cleanup).
    extract_phases: Tuple[str, ...] = tuple(EXTRACT_PHASES)
    write_phases: Tuple[str, ...] = tuple(WRITE_PHASES)

    # Runtime tools this plugin needs.  Probed on a worker thread when
    # the user picks this manufacturer in the GUI; results render as
    # `[✓] gpg [✗] partclone` indicators with hover tooltips.  Default
    # is empty (no prereqs to verify — e.g. PB's stdlib-only flow).
    prerequisites: Tuple[Prerequisite, ...] = ()

    # Optional: GitHub repo override.  When None, the core update checker
    # uses :data:`core.config.GITHUB_REPO`.
    update_repo: Optional[str] = None

    @abstractmethod
    def detect(self, path):
        """Return a :class:`Game` if this manufacturer claims *path*, else None."""

    # ------------------------------------------------------------------
    # Pipeline factories — implement those your capabilities advertise.
    # ------------------------------------------------------------------

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        raise NotImplementedError(
            f"{self.display} does not implement an Extract pipeline.")

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        raise NotImplementedError(
            f"{self.display} does not implement a Write pipeline.")

    def apply_delta(self, assets_dir, delta_path,
                    log_cb=None, progress_cb=None):
        """Returns ``(overwritten, added, total)``."""
        raise NotImplementedError(
            f"{self.display} does not implement apply-delta.")

    # ------------------------------------------------------------------
    # Misc UI hints — override if you want non-default phrasing.
    # ------------------------------------------------------------------

    def extract_input_help(self) -> str:
        return f"Select a {self.display} input file."

    def write_install_help(self) -> Optional[str]:
        """Optional 'How to install' text shown beneath the Write button."""
        return None


# ---------------------------------------------------------------------------
# Registry storage
# ---------------------------------------------------------------------------

_REGISTRY: List[Manufacturer] = []


def register_manufacturer(mfr: Manufacturer):
    if any(m.key == mfr.key for m in _REGISTRY):
        return  # idempotent — plugin re-imports during tests are fine
    _REGISTRY.append(mfr)


def all_manufacturers() -> List[Manufacturer]:
    """Return every registered manufacturer sorted alphabetically by display
    name (so the GUI dropdown order is stable and easy to scan)."""
    return sorted(_REGISTRY, key=lambda m: m.display.lower())


def get_manufacturer(key: str) -> Optional[Manufacturer]:
    for m in _REGISTRY:
        if m.key == key:
            return m
    return None


def load_plugins():
    """Import every plugin module so each can call register_manufacturer()."""
    for module_name in _PLUGIN_MODULES:
        try:
            mod = importlib.import_module(module_name)
            register = getattr(mod, "register", None)
            if register:
                register()
        except Exception as e:
            # A broken plugin shouldn't take down the whole app.
            # The first-time setup may have missing optional deps.
            print(f"Warning: failed to load plugin {module_name}: {e}")


def detect_manufacturer(path):
    """Walk registered manufacturers, return the first that claims *path*.

    Returns ``(manufacturer, game)`` or ``(None, None)``.
    """
    for m in _REGISTRY:
        try:
            game = m.detect(path)
        except Exception:
            continue
        if game:
            return m, game
    return None, None
