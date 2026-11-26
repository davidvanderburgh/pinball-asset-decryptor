"""PAD-1601: Spike 1 save states are packed like Spike 2's and Spike 3's.

A raw Ghostbusters LE slot was 42 MB (26 MB of it the same qemu + game ELF in
every slot, plus criu's -v4 dump.log); packed it is 2 MB, with the binaries
kept once per title.  Proven on the emulator: a packed slot and a slot saved
by the old script both restore to the save-time DMD frame bit for bit.
These checks keep the pieces that proof rests on from quietly going away.
"""
import os

from pinball_decryptor.webui.emulate_spike1_core import DEFAULT_RIG_DIR


def _code(name):
    with open(os.path.join(DEFAULT_RIG_DIR, name), encoding="utf-8") as fh:
        return "\n".join(ln for ln in fh.read().splitlines()
                         if not ln.lstrip().startswith("#"))


def test_save_packs_the_checkpoint_after_the_thaw():
    save = _code("s1savestate.sh")
    assert "zstd -3 -T0" in save
    assert '"$STAGE/slot.tar.zst"' in save
    # slot.meta and restore.env stay plain: the lister and the restore's
    # title check read them without unpacking
    assert "--exclude=./slot.meta --exclude=./restore.env" in save
    # packing runs after the guest is thawed, so the save feels the same
    assert save.index('kill -CONT "$PID"', save.index("--leave-stopped")) \
        < save.index("zstd -3 -T0")


def test_save_keeps_the_binaries_once_per_title():
    save = _code("s1savestate.sh")
    assert '"$GSAVES/.bin/$sum.zst"' in save
    # the restore.env line is the same shape old slots carry
    assert 'echo "bin $sum $f $name" >> "$STAGE/restore.env"' in save
    # no zstd: the old raw layout, bin/ in the slot
    assert 'cp -f "$f" "$STAGE/bin/$name"' in save


def test_dump_log_goes_when_good_and_stays_on_a_failure():
    save = _code("s1savestate.sh")
    fail = save.index("[s1save] FAILED")
    good = save.index('rm -f "$STAGE/dump.log"')
    assert fail < good
    assert '"$S1_WORK/s1save.failed.log"' in save[fail:good]


def test_a_failed_save_keeps_the_earlier_slot():
    save = _code("s1savestate.sh")
    assert '-D "$STAGE"' in save
    # the old slot is only removed once the new dump is good and packed
    assert save.index('rm -rf "$DDIR"') > save.index("Dumping FAILED")
    assert 'mv "$STAGE" "$DDIR"' in save


def test_restore_reads_packed_and_raw_slots():
    restore = _code("s1restorestate.sh")
    assert '[ -f "$DDIR/slot.tar.zst" ]' in restore
    assert 'zstd -d -q -c "$DDIR/slot.tar.zst" | tar -C "$LOADDIR" -xf -' in restore
    # raw (pre-PAD-1601) slots restore in place
    assert 'IDIR=$DDIR' in restore
    assert '-D "$IDIR"' in restore
    # unpacking happens BEFORE the live guest is replaced
    assert restore.index("slot.tar.zst") < restore.index("live guest $OLD replaced")
    assert "trap 'rm -rf \"$LOADDIR\"' EXIT" in restore


def test_restore_reinstalls_from_slot_or_shared_store_with_a_sha_check():
    restore = _code("s1restorestate.sh")
    assert '"$IDIR/bin/$name"' in restore
    assert '"$STORE/$sum.zst"' in restore
    assert '[ "$(sha1sum "$tmp" | cut -d\' \' -f1)" = "$sum" ]' in restore


def test_slots_count_and_prune_the_shared_store():
    slots = _code("s1slots.sh")
    assert '"$SAVES"/*/.bin/' in slots          # counted once in total|
    assert "prune_store" in slots.split("delete)", 1)[1]
    assert "prune)" in slots
    save = _code("s1savestate.sh")
    assert 's1slots.sh" prune "$CLABEL"' in save
