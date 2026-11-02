"""PAD's edited SAM game into a Visual Pinball table's ROM set (PAD-943):
tools/spike2_emu/vpx/vpxsam.py.

What is worth failing on, none of it needing VPinMAME or libpinmame:
  * THE ROM SET IS THE TABLE'S, OR THE ONE VERSION THE FILE'S SIZE FITS. CSI's
    six versions are all 31596480 bytes, so a bare .bin of that size is
    refused with the choices; the table's cGameName or --rom picks; a .bin of
    another version's size than the ROM set's is refused (PinMAME checks the
    length, the table's rules expect its version).
  * THE ZIP IS WHAT PINMAME LOADS: <romset>.zip, the .bin under the member
    name sam_games.py gives that version, stored; the stock zip kept once as
    <romset>.stock.zip and put back by `restore`.
  * WHERE: --roms, the kit's record, VPinMAME's rompath, a roms folder beside
    the tables folder - in that order.
  * NO VPinMAME: ignore_rom_crc is not written, and the command says so.
"""
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VPX = os.path.join(ROOT, "tools", "spike2_emu", "vpx")
for p in (os.path.join(ROOT, "tools", "spike2_emu"), VPX):
    if p not in sys.path:
        sys.path.insert(0, p)
pytestmark = pytest.mark.skipif(not os.path.isdir(VPX), reason="rig not present")

CSI_SIZE = 31596480          # every CSI version
AVR_200_SIZE = 30751908      # Avatar 1.1 / 1.2 LE / 2.0


@pytest.fixture(scope="module")
def vs():
    return pytest.importorskip("vpxsam")


def _bin(tmp_path, size, name="game.bin"):
    p = tmp_path / name
    with open(p, "wb") as f:
        f.truncate(size)
    return str(p)


def test_the_apps_sam_table_is_read_by_path(vs):
    db = vs.sam_games()
    assert db["csi"]["romsets"]["csi_240"][0] == "csi_240a.bin"
    assert vs.romset_member("csi_240") == ("csi", "csi_240a.bin", CSI_SIZE)
    assert vs.romset_member("nope_100") is None
    assert [rs for _k, rs, _m in vs.romsets_by_size(CSI_SIZE)] == [
        "csi_102", "csi_104", "csi_200", "csi_210", "csi_230", "csi_240"]


def test_a_size_several_versions_share_needs_the_table_or_rom(vs, tmp_path):
    b = _bin(tmp_path, CSI_SIZE)
    with pytest.raises(RuntimeError, match="fits csi_102, csi_104.*--table"):
        vs.choose_romset(b)
    assert vs.choose_romset(b, rom="csi_240") == ("csi", "csi_240", "csi_240a.bin")
    with pytest.raises(RuntimeError, match="not a SAM ROM set"):
        vs.choose_romset(b, rom="csi_999")
    with pytest.raises(RuntimeError, match="no SAM game file"):
        vs.choose_romset(_bin(tmp_path, 12345, "odd.bin"))


def test_the_edit_must_be_the_rom_sets_version(vs, tmp_path):
    b = _bin(tmp_path, AVR_200_SIZE)
    # Avatar 2.0's size is 1.1's and the LE 1.2's too; 1.06 is another
    assert vs.choose_romset(b, rom="avr_200")[1] == "avr_200"
    with pytest.raises(RuntimeError, match="avr_106 is Avatar's 32321972-byte file; game.bin is 30751908"):
        vs.choose_romset(b, rom="avr_106")


def test_the_table_names_its_rom_set(vs, tmp_path, monkeypatch):
    import vpxfile

    class T:
        def __init__(self, path):
            self.path = path

        def script(self):
            return 'Option Explicit\nConst cGameName="csi_240",UseSolenoids=1\n' if "csi" in self.path \
                else "Const BallSize = 50\n"
    monkeypatch.setattr(vpxfile, "VpxTable", T)
    assert vs.table_romset("csi.vpx") == "csi_240"
    assert vs.table_romset("other.vpx") == ""
    b = _bin(tmp_path, CSI_SIZE)
    assert vs.choose_romset(b, table="csi.vpx")[1] == "csi_240"
    with pytest.raises(RuntimeError, match="names no cGameName"):
        vs.choose_romset(b, table="other.vpx")


def test_write_keeps_the_stock_once_and_restore_puts_it_back(vs, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    with zipfile.ZipFile(roms / "csi_240.zip", "w") as z:
        z.writestr("csi_240a.bin", b"stock")
        z.writestr("CSIreadme.txt", b"readme")
    b = _bin(tmp_path, CSI_SIZE)
    said = []
    out = vs.write_romset(b, "csi_240", "csi_240a.bin", str(roms), log=said.append)
    assert out == os.path.join(str(roms), "csi_240.zip")
    with zipfile.ZipFile(out) as z:
        info = z.infolist()
        assert [i.filename for i in info] == ["csi_240a.bin"]
        assert info[0].file_size == CSI_SIZE and info[0].compress_type == zipfile.ZIP_STORED
    with zipfile.ZipFile(roms / "csi_240.stock.zip") as z:
        assert z.read("csi_240a.bin") == b"stock"
    assert any("kept" in s for s in said)
    # a second write does not overwrite the kept stock with the edit
    vs.write_romset(b, "csi_240", "csi_240a.bin", str(roms), log=said.append)
    with zipfile.ZipFile(roms / "csi_240.stock.zip") as z:
        assert z.read("csi_240a.bin") == b"stock"
    assert vs.restore_romset("csi_240", str(roms), log=said.append)
    with zipfile.ZipFile(roms / "csi_240.zip") as z:
        assert z.read("csi_240a.bin") == b"stock"
    assert not (roms / "csi_240.stock.zip").exists()
    assert not vs.restore_romset("csi_240", str(roms), log=said.append)


def test_the_roms_folder_is_looked_for_in_order(vs, tmp_path, monkeypatch):
    kit_roms = tmp_path / "kitroms"
    reg_roms = tmp_path / "regroms"
    tables = tmp_path / "vp" / "tables"
    beside = tmp_path / "vp" / "roms"
    for d in (kit_roms, reg_roms, tables, beside):
        d.mkdir(parents=True)
    import padlaunch
    assert vs.roms_folder(str(tmp_path)) == (str(tmp_path), "given")
    monkeypatch.setattr(padlaunch, "kit_load", lambda: {"vpm_roms": str(kit_roms), "tables": str(tables)})
    monkeypatch.setattr(vs, "vpm_rompath", lambda: str(reg_roms))
    assert vs.roms_folder() == (str(kit_roms), "the kit's record")
    monkeypatch.setattr(padlaunch, "kit_load", lambda: {"tables": str(tables)})
    assert vs.roms_folder() == (str(reg_roms), "VPinMAME's rompath")
    monkeypatch.setattr(vs, "vpm_rompath", lambda: "")
    assert vs.roms_folder() == (str(beside), "beside the tables folder")
    monkeypatch.setattr(padlaunch, "kit_load", lambda: {})
    assert vs.roms_folder()[0] == ""


def test_without_vpinmame_the_crc_flag_is_not_written(vs, monkeypatch):
    monkeypatch.setattr(vs, "vpm_registered", lambda: False)
    said = []
    assert vs.set_ignore_crc("csi_240", log=said.append) is False
    assert "not registered" in said[0]


def test_the_command_writes_and_reports(vs, tmp_path, monkeypatch, capsys):
    import padlaunch
    roms = tmp_path / "roms"
    roms.mkdir()
    b = _bin(tmp_path, CSI_SIZE, "csi_240a_pad.bin")
    saved = {}
    monkeypatch.setattr(padlaunch, "kit_load", lambda: dict(saved))
    monkeypatch.setattr(padlaunch, "kit_save", saved.update)
    monkeypatch.setattr(vs, "vpm_registered", lambda: False)
    assert vs.main([b, "--rom", "csi_240", "--roms", str(roms)]) == 0
    out = capsys.readouterr().out
    assert "ROM set csi_240 (CSI)" in out and "not registered" in out
    assert zipfile.ZipFile(roms / "csi_240.zip").namelist() == ["csi_240a.bin"]
    assert saved["vpm_roms"] == str(roms)             # --roms is remembered
    assert vs.main([b, "--roms", str(roms)]) == 1     # six CSI versions: which?
    assert vs.main([str(tmp_path / "missing.bin")]) == 2
