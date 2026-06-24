"""Data East manufacturer plugin (classic DMD era, 1991-1994).

Data East / Sega / Stern are one hardware lineage that all run in
PinMAME; this plugin family follows the Williams model (MAME ROM zip
in).  Data East is the first brand entry.  The :data:`games.GAME_DB`
catalogue (auto-generated from PinMAME's ``degames.c``) also carries the
early Sega-on-DE-hardware titles; each brand entry exposes only its own
``manufacturer`` slice, so they land under separate picker cards.
"""

from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                               register_manufacturer)
from .formats import detect_game
from .games import GAME_DB
from .pipeline import PHASES, ExtractPipeline


def _slice(brand):
    """The {key: info} sub-catalogue for one manufacturer brand."""
    return {k: v for k, v in GAME_DB.items() if v["manufacturer"] == brand}


class _ClassicManufacturer(Manufacturer):
    """Shared behaviour for the PinMAME classic-DMD brand entries."""

    brand = ""               # the GAME_DB ``manufacturer`` value to expose
    badge = "EXTRACT ONLY"
    beta = True
    capabilities = Capabilities(extract=True)
    extract_phases = PHASES

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

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              **kwargs):
        return ExtractPipeline(
            input_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            game_db=self._game_db)

    def extract_input_help(self):
        return ("Pick a MAME-format ROM zip for a Data East / Sega DMD "
                "game — e.g. `lw3_208.zip` (Lethal Weapon 3), "
                "`jupk_513.zip` (Jurassic Park), `tftc_303.zip` (Tales "
                "from the Crypt).  Extract identifies the game and unpacks "
                "its ROM set; DMD-animation + audio extraction are coming.")


class DataEastManufacturer(_ClassicManufacturer):
    key = "data_east"
    display = "Data East"
    brand = "Data East"
    input_spec = InputSpec(
        label="Data East MAME ROM zips", extensions=(".zip",))


def register():
    register_manufacturer(DataEastManufacturer())
