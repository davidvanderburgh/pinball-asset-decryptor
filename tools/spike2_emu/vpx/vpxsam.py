#!/usr/bin/env python3
"""vpxsam.py - PAD's edited Stern SAM game into a Visual Pinball table's
ROM set (PAD-943).

A SAM table runs the REAL game: Visual PinMAME has the SAM core, and the
table's script names the ROM set (`cGameName = "csi_240"`) VPinMAME loads
from `<roms>\\csi_240.zip`, a zip holding Stern's own .bin under the name
PinMAME knows (`csi_240a.bin`). PAD's Write tab produces that same .bin
with the sounds and pictures replaced, the file's size unchanged. So the
hand-off is: the edited .bin into a `<romset>.zip` in VPinMAME's roms
folder, under the member name PinMAME loads, and the game's "skip ROM
verification" flag set so VPinMAME does not stop on the changed checksum.

    padvpx sam "<edited game.bin>" [--table "<x.vpx>" | --rom <romset>]
               [--roms <folder>] [--keep]

Which ROM set: `--rom`, else the table's `cGameName`, else the one SAM
version of the .bin's size PinMAME knows (several: it says which, and asks
for the table). The .bin must be the version the ROM set is - PinMAME
checks the length and the table's rules expect it - so a table on
acd_168h takes an edit of 1.68's file, not 1.70's.

Which folder: `--roms`, else the kit's record (`~/.pad-vpx.json`
`vpm_roms`), else VPinMAME's own rompath (HKCU\\Software\\Freeware\\Visual
PinMame\\globals), else a `roms` folder beside the kit's tables folder.
The stock zip there is kept as `<romset>.stock.zip` the first time (so a
later `--keep`-less write of the stock file puts it back), and the per-game
`ignore_rom_crc` is written only where VPinMAME is registered.

Nothing here needs the app running; the member names come from the app's
own SAM table (plugins/pinmame_classic/sam_games.py, read by path).
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import padlaunch  # noqa: E402

VPM_KEY = r"Software\Freeware\Visual PinMame"
#: a table script's ROM set line: Const cGameName = "csi_240"
CGAME = re.compile(r'cGameName\s*=\s*"([A-Za-z0-9_]+)"')


def sam_games():
    """SAM_GAME_DB, by path (the plugin package's __init__ pulls in the
    codec stack the kit does not need): {key: {"display", "romsets":
    {romset: (member, crc, size, title)}}}."""
    app = os.path.dirname(os.path.dirname(os.path.abspath(padlaunch.rig_dir())))
    for base in (app, os.path.dirname(RIG)):
        path = os.path.join(base, "pinball_decryptor", "plugins", "pinmame_classic", "sam_games.py")
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("_sam_games", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.SAM_GAME_DB
    raise RuntimeError("the app's SAM game table (pinball_decryptor/plugins/pinmame_classic/sam_games.py) "
                       "is not beside the kit")


def romsets_by_size(size, db=None):
    """[(key, romset, member)] of every SAM version whose .bin is `size` bytes."""
    db = db or sam_games()
    out = []
    for key, info in db.items():
        for rs, (member, _crc, sz, _title) in info["romsets"].items():
            if sz == size:
                out.append((key, rs, member))
    return sorted(out)


def romset_member(romset, db=None):
    """(key, member, size) for a ROM set PinMAME knows, or None."""
    db = db or sam_games()
    for key, info in db.items():
        rs = info["romsets"].get(romset)
        if rs:
            return key, rs[0], rs[2]
    return None


def table_romset(table_path):
    """The ROM set a table's script names (cGameName), or ""."""
    import vpxfile
    try:
        script = vpxfile.VpxTable(table_path).script()
    except Exception as exc:                                # noqa: BLE001
        raise RuntimeError("cannot read the table %s: %s" % (table_path, exc))
    m = CGAME.search(script)
    return m.group(1) if m else ""


def vpm_rompath():
    """VPinMAME's own roms folder from its registry, or ""."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, VPM_KEY + r"\globals") as k:
            v = winreg.QueryValueEx(k, "rompath")[0]
            return v if isinstance(v, str) and os.path.isdir(v) else ""
    except (ImportError, OSError):
        return ""


def vpm_registered():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, VPM_KEY):
            return True
    except (ImportError, OSError):
        return False


def roms_folder(given=None):
    """Where the ROM sets go, and how that was decided: (folder, how)."""
    if given:
        return given, "given"
    kit = padlaunch.kit_load()
    if kit.get("vpm_roms") and os.path.isdir(kit["vpm_roms"]):
        return kit["vpm_roms"], "the kit's record"
    reg = vpm_rompath()
    if reg:
        return reg, "VPinMAME's rompath"
    tables = kit.get("tables") or ""
    beside = os.path.join(os.path.dirname(tables.rstrip("\\/")), "roms") if tables else ""
    if beside and os.path.isdir(beside):
        return beside, "beside the tables folder"
    return "", "nowhere: say --roms <folder>"


def remember_roms(folder):
    kit = padlaunch.kit_load()
    kit["vpm_roms"] = folder
    padlaunch.kit_save(kit)


def set_ignore_crc(romset, log=print):
    """VPinMAME's per-game "skip ROM verification" (ignore_rom_crc), so the
    changed checksum is not a stop. Only where VPinMAME is registered;
    True when written."""
    if sys.platform != "win32" or not vpm_registered():
        log("VPinMAME is not registered on this PC: set the game's 'Skip ROM verification' "
            "in its options when it is (or the changed checksum stops it)")
        return False
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, VPM_KEY + "\\" + romset) as k:
        winreg.SetValueEx(k, "ignore_rom_crc", 0, winreg.REG_DWORD, 1)
    log("VPinMAME: %s skips ROM verification (ignore_rom_crc = 1)" % romset)
    return True


def choose_romset(bin_path, table=None, rom=None, db=None):
    """The ROM set the .bin goes into: (key, romset, member); raises with
    what to say when it cannot be told or does not fit."""
    db = db or sam_games()
    size = os.path.getsize(bin_path)
    fits = romsets_by_size(size, db)
    if rom:
        found = romset_member(rom, db)
        if not found:
            raise RuntimeError("%s is not a SAM ROM set PinMAME knows" % rom)
        key, member, want = found
        if want != size:
            raise RuntimeError("%s is %s's %d-byte file; %s is %d bytes - the edit must be of the "
                               "version the table's ROM set is" % (
                                   rom, db[key]["display"], want, os.path.basename(bin_path), size))
        return key, rom, member
    if table:
        named = table_romset(table)
        if not named:
            raise RuntimeError("%s names no cGameName; say --rom" % os.path.basename(table))
        return choose_romset(bin_path, rom=named, db=db)
    if len(fits) == 1:
        return fits[0]
    if not fits:
        raise RuntimeError("%d bytes is no SAM game file PinMAME knows" % size)
    raise RuntimeError("%d bytes fits %s: say which with --table <the table> or --rom" % (
        size, ", ".join(rs for _k, rs, _m in fits)))


def write_romset(bin_path, romset, member, roms_dir, keep=True, log=print):
    """`<roms_dir>/<romset>.zip` holding the .bin as `member`; the stock
    zip there kept once as `<romset>.stock.zip`. Returns the zip's path."""
    os.makedirs(roms_dir, exist_ok=True)
    out = os.path.join(roms_dir, romset + ".zip")
    stock = os.path.join(roms_dir, romset + ".stock.zip")
    if keep and os.path.isfile(out) and not os.path.isfile(stock):
        shutil.copy2(out, stock)
        log("kept the ROM set that was there as %s" % os.path.basename(stock))
    tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        with dst.open(member, "w", force_zip64=True) as w, open(bin_path, "rb") as r:
            shutil.copyfileobj(r, w, 1 << 20)
    os.replace(tmp, out)
    log("wrote %s (%s, %d bytes)" % (out, member, os.path.getsize(bin_path)))
    return out


def restore_romset(romset, roms_dir, log=print):
    """The stock zip back in place, when one was kept."""
    out = os.path.join(roms_dir, romset + ".zip")
    stock = os.path.join(roms_dir, romset + ".stock.zip")
    if not os.path.isfile(stock):
        log("no %s kept in %s" % (os.path.basename(stock), roms_dir))
        return False
    os.replace(stock, out)
    log("%s is the stock ROM set again" % out)
    return True


def main(argv):
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    opt = {}
    for flag in ("--table", "--rom", "--roms"):
        if flag in args:
            i = args.index(flag)
            opt[flag[2:]] = args[i + 1]
            del args[i:i + 2]
    keep = "--keep" in args or "--no-keep" not in args
    args = [a for a in args if a not in ("--keep", "--no-keep")]
    if args[0] == "restore":
        folder, how = roms_folder(opt.get("roms"))
        if not folder:
            print("no roms folder (%s)" % how)
            return 2
        return 0 if restore_romset(args[1], folder) else 1
    bin_path = args[0]
    if not os.path.isfile(bin_path):
        print("no such file: %s" % bin_path)
        return 2
    try:
        key, romset, member = choose_romset(bin_path, opt.get("table"), opt.get("rom"))
    except RuntimeError as exc:
        print(exc)
        return 1
    folder, how = roms_folder(opt.get("roms"))
    if not folder:
        print("no roms folder for the ROM set (%s)" % how)
        return 2
    print("%s -> ROM set %s (%s), roms folder %s (%s)" % (
        os.path.basename(bin_path), romset, sam_games()[key]["display"], folder, how))
    out = write_romset(bin_path, romset, member, folder, keep=keep)
    set_ignore_crc(romset)
    if opt.get("roms"):
        remember_roms(folder)
    print(json.dumps({"zip": out, "romset": romset, "member": member, "roms": folder}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
