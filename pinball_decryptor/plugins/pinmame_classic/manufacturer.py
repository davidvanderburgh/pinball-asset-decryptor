"""Data East manufacturer plugin (classic DMD era, 1991-1994).

Data East / Sega / Stern are one hardware lineage that all run in
PinMAME; this plugin family follows the Williams model (MAME ROM zip
in).  Data East is the first brand entry.  The :data:`games.GAME_DB`
catalogue (auto-generated from PinMAME's ``degames.c``) also carries the
early Sega-on-DE-hardware titles; each brand entry exposes only its own
``manufacturer`` slice, so they land under separate picker cards.
"""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                               Prerequisite, register_manufacturer)
from . import capture as _capture
from .formats import detect_game
from .games import GAME_DB


def _slice(brand):
    """The {key: info} sub-catalogue for one manufacturer brand."""
    return {k: v for k, v in GAME_DB.items() if v["manufacturer"] == brand}


class _ClassicManufacturer(Manufacturer):
    """Shared behaviour for the PinMAME classic-DMD brand entries.

    These games store their DMD animations *compressed* in the DMD ROM
    (decodable only by the emulated firmware, see ``docs/DE_DMD_RE.md``),
    so extraction is **capture-only**: libpinmame runs the game in attract
    mode and records the decoded 4-shade DMD animations + audio.  There is
    no static-decode path (raw ROM bytes hit the compressed regions and
    decode to static), so this is a capture-primary plugin (``extract``
    is False) and the GUI hides the "Basic extract" toggle.
    """

    brand = ""               # the GAME_DB ``manufacturer`` value to expose
    badge = "EXTRACT ONLY"   # consistent with Williams (the other PinMAME plugin)
    beta = True
    capabilities = Capabilities(extract=False, capture=True)
    extract_phases = _capture.PHASES
    capture_phases = _capture.PHASES
    prerequisites = (
        Prerequisite(
            name="ffmpeg", where="host", probe="ffmpeg -version",
            reason="Rendering the captured DMD animations into MP4s.",
            install_hint=(
                "winget install Gyan.FFmpeg  (Windows)\n"
                "brew install ffmpeg          (macOS)\n"
                "apt-get install ffmpeg       (Linux)")),
    )

    def __init__(self):
        self._game_db = _slice(self.brand)
        self.games = tuple(sorted(
            (Game(key=k, display=v["display"], manufacturer_key=self.key,
                  notes=f"{v['year']}, {v['dmd']} DMD")
             for k, v in self._game_db.items()),
            key=lambda g: g.display.lower()))

    def detect(self, path):
        key = detect_game(path, self._game_db)
        if key is None:
            return None
        info = self._game_db[key]
        return Game(
            key=key, display=info["display"], manufacturer_key=self.key,
            notes=f"{info['manufacturer']} {info['year']}, {info['dmd']} DMD")

    def make_capture_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              **kwargs):
        return _capture.CapturePipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            game_db=self._game_db,
            duration_seconds=kwargs.get("duration_seconds", 180.0),
            frame_cb=kwargs.get("frame_cb"),
            # No switch-matrix diagnostic: these games are captured in
            # attract mode only (no WPC-style switch poking), so the
            # "Generic WPC" matrix would just be confusing.
            capture_ready_cb=None)

    def extract_input_help(self):
        return (f"Pick a MAME-format ROM zip for a {self.display} DMD "
                "game (named by its romset, e.g. `apollo13.zip`, "
                "`gldneye.zip`, `lw3_208.zip`).  Extract runs the game in "
                "attract mode (libpinmame) and records the DMD animations "
                "+ audio as the firmware renders them — the only way to "
                "get these games' compressed DMD animations.")


class DataEastManufacturer(_ClassicManufacturer):
    key = "data_east"
    display = "Data East"
    brand = "Data East"
    input_spec = InputSpec(
        label="Data East MAME ROM zips", extensions=(".zip",))


class SegaManufacturer(_ClassicManufacturer):
    key = "sega"
    display = "Sega"
    brand = "Sega"
    input_spec = InputSpec(
        label="Sega MAME ROM zips", extensions=(".zip",))


def register():
    register_manufacturer(DataEastManufacturer())
    register_manufacturer(SegaManufacturer())
