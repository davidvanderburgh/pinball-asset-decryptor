"""The shared card store (PAD-651): one ext4 disk file on the NVMe mounted into every distro at /mnt/wsl/cards,
where cardmount.sh keeps its cache when it is there; the library pre-cached once; old caches migrated."""
import os
import re

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")


def _text(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def test_cardmount_keeps_its_cache_in_the_shared_store_when_it_is_mounted():
    cm = _text("cardmount.sh")
    blk = cm[cm.index("# THE SHARED CARD STORE (PAD-651)"):cm.index('FUSE2FS="$PREFIX/usr/bin/fuse2fs"')]
    assert 'if [ -n "${PAD_CARD_CACHE_DIR:-}" ]; then' in blk and "CACHE=$PAD_CARD_CACHE_DIR" in blk
    assert 'elif [ -d /mnt/wsl/cards/cardcache ] && mountpoint -q /mnt/wsl/cards 2>/dev/null; then' in blk
    assert "CACHE=/mnt/wsl/cards/cardcache" in blk
    assert "CACHE=$PAD_HOME/cardcache" in blk                     # the fallback: as it always was
    assert 'if [ "${1:-}" = "--cache-dir" ]; then' in cm and 'echo "$CACHE"; exit 0' in cm


def test_the_stager_and_the_multicard_builder_know_the_store():
    cs = _text("cardstage.sh")
    assert '"$PAD_HOME"/cardcache/*|/mnt/wsl/cards/cardcache/*|"${PAD_CARD_CACHE_DIR:-/nonexistent}"/*)' in cs
    mk = _text("mkmulticard.py")
    assert 'os.environ.get("PAD_CARD_CACHE_DIR") or (' in mk
    assert '"/mnt/wsl/cards/cardcache" if os.path.isdir("/mnt/wsl/cards/cardcache")' in mk


def test_the_store_script_attaches_by_name_and_registers_the_logon_task():
    ps = _text("cardstore.ps1")
    assert "--vhd --bare" in ps and "--vhd --name $Name" in ps and "$Name = 'cards'" in ps
    assert "mkfs.ext4 -q -L $Name -m 0 $dev" in ps
    assert "schtasks /Create /F /TN 'PAD card store' /SC ONLOGON /RL HIGHEST /TR $ps" in ps
    # the disk steps run elevated; the distro's files are touched unelevated
    assert "Start-Process powershell.exe -Verb RunAs" in ps
    assert ps.index("Elevate 'create'") < ps.index('mkfs.ext4') < ps.index("Elevate 'remount'")
    assert "chmod 1777 $MountPoint $MountPoint/cardcache" in ps
    assert "\t" not in ps                                          # a path with a tab in it bit once


def test_precache_reads_only_the_library_folder_under_the_copy_lock():
    pc = _text("precache.sh")
    assert "LIB=${1:-/mnt/d/Pinball/images/Stern/spike2}" in pc
    assert "find \"$LIB\" -maxdepth 1 -type f -name '*.raw'" in pc        # never the older versions subfolder
    assert "COPY_LOCK=/mnt/wsl/pad-cardstage-copy.lock" in pc              # the sweeps' own lock
    assert 'flock 9; bash "$RIG/cardmount.sh" "$card" --cache-now' in pc
    assert 'CACHE=$(bash "$RIG/cardmount.sh" --cache-dir' in pc


def test_cachemigrate_moves_only_valid_entries_and_drops_stale_ones():
    cmg = _text("cachemigrate.sh")
    assert "NEW=$(bash \"$RIG/cardmount.sh\" --cache-dir" in cmg
    assert '[ "$(stat -c \'%s %Y\' "$img" 2>/dev/null)" != "$rest" ]' in cmg       # the .src stamp must still hold
    assert "cp --sparse=always -p" in cmg
    # the old entry goes only after the new one is in place (the last rm is the move branch's)
    assert cmg.index('mv -f "$NEW/$label.raw.partial" "$NEW/$label.raw"') < cmg.rindex('rm -f "$raw" "$src"')
    assert 'pgrep -f "fuse2fs.*$label"' in cmg                                  # never a card a run has mounted
    assert "OLD=${1:-${PAD_HOME:-$HOME}/cardcache}" in cmg                      # runs without padpath.sh
