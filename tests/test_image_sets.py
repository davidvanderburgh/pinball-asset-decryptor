"""IMAGE SETS: a scene's variants, the one the operator's IMAGE SET picks read in its place.

plugins/stern/scene_variants.py stages each variant's scene file and ``scenes.cfg``; the mode runtime
(pad_mode_runtime.c "IMAGE SETS") re-points the game program's fopen64 and opens a listed scene as its variant's
file. These tests hold the two sides to one table: the names, the line grammar, where the files are read from, and
that the rig and the card installer carry them."""
import os
import re
import struct
import sys

import pytest

from pinball_decryptor.plugins.stern import scene_variants as SV

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk")
CARD = "/godzilla_le/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e/scene.radium"


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def _runtime():
    return _read("tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")


def test_normalise_keeps_only_real_variants():
    raw = {"names": ["Dark"], "force": 9,
           "scenes": {CARD: {"2": {"card": True}, "1": {"card": True}, "x": {}, "17": {"card": True}},
                      "/not/a/scene.bin": {"2": {"card": True}}}}
    got = SV.normalise(raw)
    assert list(got["scenes"]) == [CARD]
    assert list(got["scenes"][CARD]) == [2]          # set 1 is the scene's own; 17 is past MAX_SETS
    assert got["names"] == ["Dark", "Set 2"]          # one name per set, the missing ones made up
    assert got["force"] == 0                          # a forced set past the sets is dropped
    assert SV.normalise({"scenes": {}}) is None
    assert SV.normalise(None) is None


def test_names_and_tail():
    assert SV.file_name(CARD, 3) == "scn_cac32730af42_3.radium"
    # from the scene's folder on: a Premium card's title folder (godzilla_le) still matches
    assert SV.tail(CARD) == "cac32730af42b9d26d26c4bb6e667b07da53113e/scene.radium"
    with pytest.raises(SV.SceneVariantError):
        SV.scene_id("/godzilla_le/assets/lcd/hud.radium")


def test_cfg_text_grammar():
    text = SV.cfg_text({"fopen64": 0x7090A4, "eglSwapBuffers": 0x709564}, 0x800000, 3,
                       [(CARD, 2, SV.file_name(CARD, 2))], only=True, force=2)
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines == ["only",
                     "got\tfopen64\t0x007090a4",
                     "got\teglSwapBuffers\t0x00709564",
                     "setting\t0x00800000\t3",
                     "scene\t%s\t2\tscn_cac32730af42_2.radium" % SV.tail(CARD),
                     "force\t2"]


def _elf_with_imports(names):
    """A minimal 32-bit ARM executable whose PLT relocations import *names* (what import_slots reads)."""
    strtab = b"\x00" + b"".join(n.encode() + b"\x00" for n in names)
    symtab = b"\x00" * 16
    offs, o = [], 1
    for n in names:
        offs.append(o)
        o += len(n) + 1
        symtab += struct.pack("<IIIBBH", offs[-1], 0, 0, 0x12, 0, 0)
    base = 0x10000
    hdr = 52 + 32 * 2
    p_str = hdr
    p_sym = p_str + len(strtab)
    p_rel = p_sym + len(symtab)
    rel = b"".join(struct.pack("<II", 0x20000 + 4 * i, ((i + 1) << 8) | 22) for i in range(len(names)))
    p_dyn = p_rel + len(rel)
    dyn = struct.pack("<iIiIiIiIiIiI", 5, base + p_str, 6, base + p_sym, 23, base + p_rel, 2, len(rel),
                      20, 17, 0, 0)
    end = p_dyn + len(dyn)
    eh = b"\x7fELF\x01\x01\x01" + b"\x00" * 9 + struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, base, 52, 0, 0, 52, 32, 2,
                                                            40, 0, 0)
    ph = struct.pack("<8I", 1, 0, base, base, end, end, 5, 0x1000)
    ph += struct.pack("<8I", 2, p_dyn, base + p_dyn, base + p_dyn, len(dyn), len(dyn), 6, 4)
    return eh + ph + strtab + symtab + rel + dyn


def test_import_slots_and_stage(tmp_path):
    elf = _elf_with_imports(["puts", "fopen64", "eglSwapBuffers"])
    assert SV.import_slots(elf) == {"fopen64": 0x20004, "eglSwapBuffers": 0x20008}
    with pytest.raises(SV.SceneVariantError):
        SV.import_slots(_elf_with_imports(["fopen64"]))
    own = tmp_path / "proj" / "Image sets"
    own.mkdir(parents=True)
    (own / "light.radium").write_bytes(b"\x01" + b"L" * 64)
    sets = SV.normalise({"names": ["Dark", "Light", "Card"],
                         "scenes": {CARD: {"2": {"file": "Image sets/light.radium"}, "3": {"card": True}}}})
    said = []
    cfg, files = SV.stage(str(tmp_path / "proj"), sets, elf, lambda card: b"\x01" + b"C" * 64 if card == CARD else None,
                          str(tmp_path / "work"), live=0x900000, only=True, log=lambda m, *a: said.append(m))
    assert [os.path.basename(f) for f in files] == ["scn_cac32730af42_2.radium", "scn_cac32730af42_3.radium"]
    assert open(files[0], "rb").read().startswith(b"\x01L") and open(files[1], "rb").read().startswith(b"\x01C")
    text = open(cfg, encoding="ascii").read()
    assert "setting\t0x00900000\t3" in text and text.count("\nscene\t") == 2


def test_stage_leaves_out_a_variant_it_cannot_read(tmp_path):
    elf = _elf_with_imports(["fopen64", "eglSwapBuffers"])
    sets = SV.normalise({"scenes": {CARD: {"2": {"file": "missing.radium"}}}})
    said = []
    assert SV.stage(str(tmp_path), sets, elf, lambda c: None, str(tmp_path / "w"),
                    log=lambda m, *a: said.append(m)) == ("", [])
    assert any("left out" in m for m in said)


def test_runtime_reads_the_same_table():
    src = _runtime()
    files = re.search(r"SCNV_FILES\[\]\s*=\s*\{([^}]*)\}", src).group(1)
    assert '"/usr/local/padmode/%s"' % SV.CFG_NAME in files and '"/dump/%s"' % SV.CFG_NAME in files
    syms = re.search(r"SCNV_SYMS\[SCNV_GOTS\]\s*=\s*\{([^}]*)\}", src).group(1)
    assert [s.strip().strip('"') for s in syms.split(",")] == list(SV.SYMBOLS)
    # PAD-1390: the app offers no more sets than a menu setting has values; the runtime's table holds at least that
    assert SV.MAX_SETS <= int(re.search(r"#define SCNV_SETS\s+(\d+)", src).group(1))
    for word in ('str_eq(f[0], "scene")', 'str_eq(f[0], "setting")', 'str_eq(f[0], "force")',
                 'str_eq(f[0], "only")', 'str_eq(f[0], "got")'):
        assert word in src
    # armed after the picture settings, whose eglSwapBuffers it calls on to; part of the score gate's "only"
    assert src.index("    pic_arm();") < src.index("    scnv_arm();")
    assert "scnv_only ||" in src


def test_rig_and_card_installers_carry_them():
    tryit = _read("tools", "spike2_emu", "modes", "tryit.sh")
    assert 'put "$S/scenes.cfg" "$DUMP/scenes.cfg"' in tryit
    assert '"$DUMP"/scn_*.radium' in tryit                    # an earlier install's variants are cleared
    sys.path.insert(0, os.path.join(REPO, "tools", "spike2_emu"))
    try:
        import mode_install as MI
    finally:
        sys.path.pop(0)
    assert "scenes.cfg" in dict(MI.EXTRA_FILES) and "scenes.cfg" in MI.STANDALONE_FILES
    assert MI.scene_name_ok(SV.file_name(CARD, 2))
    assert not MI.scene_name_ok("scn_cac32730af42_2.bin") and not MI.scene_name_ok("scn_ZZ_2.radium")
