"""The emulator side of the boot-time code selector (item 90).

A multi-image Spike 2 card carries the primary's games partition as p3 and
each extra image's games partition as a LOGICAL partition (p7, p8...) inside
the grown extended p4 - the only room a fixed four-primary MBR has. The rig
runs the card's own selector (an ARM program, chroot'd into the rootfs before
the game) on ``PAD_SELECT=1``, mounts the partition it chose over
``games/<title>`` and execs the game exactly as a plain card run does.

TWO KINDS OF TEST, both without a card, a rootfs or WSL:

* ``parts.py`` is DRIVEN, against a synthetic image built here: an MBR with a
  real EBR chain (entry 0 relative to the EBR, the link relative to the
  extended base - the two conventions a wrong walk silently confuses), and a
  stand-in for ``debugfs`` so the strict games rule can be checked against
  the one shape that made it necessary: p5 and p6 are EMPTY ext4 on a stock
  card, and the old "no lib/usr/etc" rule would have offered /data and /dump
  as boot choices.
* the shell scripts are READ, for the shapes that make the launch safe: the
  selector runs between the device binds and ``cd "$R"`` with NO shim, the
  two exec lines are the exact bytes they were, every new line in watch.sh
  and run_game.sh sits under a ``PAD_SELECT`` guard, the savestate literals
  another test pins are still in their order, and the process the run
  starts is counted and killed the same day it exists.
"""
import io
import os
import re
import struct
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8", newline="") as fh:
        return fh.read()


def _code(text):
    """The script with its comment lines removed."""
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))


def _line_of(text, needle):
    for i, line in enumerate(text.split("\n"), 1):
        if needle in line:
            return i
    raise AssertionError("not found: %r" % needle)


def _line_exactly(text, wanted):
    """1-based line number of the first line that IS `wanted` once stripped -
    for a needle that comments quote too (`cd "$R"`)."""
    for i, line in enumerate(text.split("\n"), 1):
        if line.strip() == wanted:
            return i
    raise AssertionError("no line is exactly: %r" % wanted)


# ==========================================================================
# parts.py against a synthetic MBR + EBR chain
# ==========================================================================

SECTOR = 512
DIR, REG, LNK = 0o040755, 0o100755, 0o120777

#: The synthetic card, in sectors. Stock-shaped in miniature: p1 FAT, p2
#: rootfs, p3 games, p4 extended holding p5 (/data) and p6 (/dump) - and then
#: p7, the appended games partition of a second image, exactly where
#: mkmulticard.py puts it: its EBR one sector after the previous logical's end,
#: the partition at the next 2048-sector boundary.
P1, P2, P3 = 8192, 10240, 12288
EXT = 14336
EBR1, P5 = 14336, 16384
EBR2, P6 = 18430, 18432
EBR3, P7 = 20478, 20480
LOG_SECTORS = 2046
END = P7 + LOG_SECTORS            # 22526: first sector past the last logical


def _entry(ptype, start, count):
    return bytes([0, 0, 0, 0, ptype, 0, 0, 0]) + struct.pack("<II", start, count)


def _sector(entries):
    s = bytearray(512)
    for i, e in enumerate(entries):
        s[0x1BE + 16 * i: 0x1BE + 16 * i + 16] = e
    s[510:512] = b"\x55\xaa"
    return bytes(s)


def _write_synthetic(path):
    """MBR + three EBRs. Entry 0 of an EBR is relative to THAT EBR; the link
    (entry 1, type 0x05) is relative to the EXTENDED partition's start."""
    mbr = _sector([
        _entry(0x0C, P1, 2048),
        _entry(0x83, P2, 2048),
        _entry(0x83, P3, 2046),
        _entry(0x0F, EXT, END - EXT),
    ])
    ebr1 = _sector([
        _entry(0x83, P5 - EBR1, LOG_SECTORS),
        _entry(0x05, EBR2 - EXT, P6 + LOG_SECTORS - EBR2),
    ])
    ebr2 = _sector([
        _entry(0x83, P6 - EBR2, LOG_SECTORS),
        _entry(0x05, EBR3 - EXT, P7 + LOG_SECTORS - EBR3),
    ])
    ebr3 = _sector([
        _entry(0x83, P7 - EBR3, LOG_SECTORS),
    ])
    with open(path, "wb") as f:
        f.write(mbr)
        for lba, data in ((EBR1, ebr1), (EBR2, ebr2), (EBR3, ebr3)):
            f.seek(lba * SECTOR)
            f.write(data)
        f.truncate((END + 2) * SECTOR)


#: What `debugfs -R "ls -p"` would say for each filesystem, by byte offset.
#: The games roots carry the three symlinks the machine itself uses, which is
#: why the title directory has to be found by MODE and not by name.
FAKE_FS = {
    P2 * SECTOR: {"/": [("lib", DIR), ("usr", DIR), ("etc", DIR), ("bin", DIR)]},
    P3 * SECTOR: {"/": [("lost+found", DIR), ("spk", DIR), ("turtles_pro", DIR),
                        ("game", LNK), ("conagent", LNK), ("data", LNK)],
                  "/turtles_pro": [("game", REG), ("conagent", REG), ("data", DIR)]},
    P5 * SECTOR: {"/": [("lost+found", DIR)]},          # /data: EMPTY ext4
    P6 * SECTOR: {"/": [("lost+found", DIR)]},          # /dump: EMPTY ext4
    P7 * SECTOR: {"/": [("lost+found", DIR), ("spk", DIR), ("turtles_pro", DIR),
                        ("game", LNK)],
                  "/turtles_pro": [("game", REG), ("data", DIR)]},
}


@pytest.fixture()
def parts(monkeypatch, tmp_path):
    """parts.py with debugfs replaced by FAKE_FS, and a synthetic card."""
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import parts as mod
    fs = {k: dict(v) for k, v in FAKE_FS.items()}

    def fake_entries(path, offset, sub="/"):
        # . and .. as debugfs lists them, so a walk that forgets to drop them
        # would recurse into itself.
        d = fs.get(offset, {}).get(sub)
        if d is None:
            return None
        return [(".", DIR), ("..", DIR)] + list(d)

    monkeypatch.setattr(mod, "_entries", fake_entries)
    img = tmp_path / "multi.raw"
    _write_synthetic(str(img))
    return type("P", (), {"mod": mod, "img": str(img), "fs": fs})


def test_the_primaries_are_read_as_before(parts):
    assert parts.mod.table(parts.img) == [
        (1, 0x0C, P1, 2048), (2, 0x83, P2, 2048),
        (3, 0x83, P3, 2046), (4, 0x0F, EXT, END - EXT)]


def test_the_ebr_chain_is_walked_with_both_conventions(parts):
    """Entry 0 relative to the EBR, the link relative to the extended base.
    Verified on the stock card: EBR@14114816 says +2048 -> p5 at 14116864 and
    links +149502 -> the next EBR at 14264318. Confusing the two lands on
    zeros and ends the chain one partition early - silently."""
    assert parts.mod.logical(parts.img) == [
        (5, 0x83, P5, LOG_SECTORS, EBR1),
        (6, 0x83, P6, LOG_SECTORS, EBR2),
        (7, 0x83, P7, LOG_SECTORS, EBR3)]


def test_a_card_without_an_extended_partition_has_no_logicals(parts, tmp_path):
    img = tmp_path / "plain.raw"
    with open(str(img), "wb") as f:
        f.write(_sector([_entry(0x0C, P1, 2048), _entry(0x83, P2, 2048),
                         _entry(0x83, P3, 2046)]))
        f.truncate(P3 * SECTOR * 2)
    assert parts.mod.logical(str(img)) == []
    assert parts.mod.part_offset(str(img), 5) is None


def test_a_looping_chain_terminates(parts, tmp_path):
    """A corrupt link back to the first EBR must not walk for ever."""
    img = tmp_path / "loop.raw"
    with open(str(img), "wb") as f:
        f.write(_sector([_entry(0x83, P2, 2048), _entry(0x0F, EXT, 8192)]))
        f.seek(EBR1 * SECTOR)
        f.write(_sector([_entry(0x83, 2048, 2046), _entry(0x05, 0, 4096)]))
        f.truncate((EBR1 + 4096) * SECTOR)
    logs = parts.mod.logical(str(img))
    assert len(logs) == 1 and logs[0][0] == 5


def test_part_offsets_cover_primaries_and_logicals(parts):
    off = parts.mod.part_offset
    assert off(parts.img, 3) == P3 * SECTOR
    assert off(parts.img, 5) == P5 * SECTOR
    assert off(parts.img, 7) == P7 * SECTOR
    assert off(parts.img, 4) == EXT * SECTOR
    assert off(parts.img, 8) is None


def test_list_games_is_strict_so_empty_data_and_dump_are_not_boot_choices(parts):
    """THE HAZARD THIS RULE EXISTS FOR. identify() calls a Linux partition
    "games" when it has /spk OR none of lib/usr/etc, and p5/p6 on a stock card
    are empty ext4 - so a walk that reused that rule would offer /data and
    /dump as images to boot. games_all needs /spk AND a title dir with `game`."""
    games = parts.mod.games_all(parts.img)
    assert [(g[0], g[3]) for g in games] == [(3, ["turtles_pro"]),
                                             (7, ["turtles_pro"])]
    assert games[1][2] == P7 * SECTOR


def test_spk_alone_is_not_a_games_partition(parts):
    parts.fs[P7 * SECTOR] = {"/": [("lost+found", DIR), ("spk", DIR)]}
    assert [g[0] for g in parts.mod.games_all(parts.img)] == [3]


def test_a_symlink_named_like_a_title_is_not_a_title_directory(parts):
    """The games root has `game -> turtles_pro/game`; only a real directory
    holding `game` counts, and mode is what tells them apart."""
    parts.fs[P7 * SECTOR] = {"/": [("spk", DIR), ("turtles_pro", LNK)],
                             "/turtles_pro": [("game", REG)]}
    assert [g[0] for g in parts.mod.games_all(parts.img)] == [3]


def test_games_still_means_the_first_games_partition(parts):
    """Every existing card script mounts `--games`; a multi-image card must
    not move it off p3."""
    found = parts.mod.identify(parts.img)
    assert found["games"] == P3 * SECTOR
    assert found["rootfs"] == P2 * SECTOR
    assert "games_guessed" not in found


def _cli(parts, monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["parts.py"] + list(args) + [parts.img])
    rc = parts.mod.main()
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_list_games_one_line_per_partition(parts, monkeypatch, capsys):
    rc, out, _err = _cli(parts, monkeypatch, capsys, "--list-games")
    assert rc == 0
    assert out.splitlines() == [
        "3 %d %d turtles_pro" % (P3, P3 * SECTOR),
        "7 %d %d turtles_pro" % (P7, P7 * SECTOR)]


def test_cli_part_prints_the_byte_offset_or_fails(parts, monkeypatch, capsys):
    rc, out, _err = _cli(parts, monkeypatch, capsys, "--part", "7")
    assert (rc, out.strip()) == (0, str(P7 * SECTOR))
    rc, out, err = _cli(parts, monkeypatch, capsys, "--part", "9")
    assert rc == 1 and out == "" and "no partition 9" in err


def test_cli_games_on_a_multi_card_says_so_on_stderr_only(parts, monkeypatch, capsys):
    rc, out, err = _cli(parts, monkeypatch, capsys, "--games")
    assert rc == 0
    assert out.strip() == str(P3 * SECTOR), "stdout is the offset and nothing else"
    assert "2 games partitions" in err and "--list-games" in err


def test_cli_table_shows_logicals_and_does_not_call_data_or_dump_games(
        parts, monkeypatch, capsys):
    rc, out, _err = _cli(parts, monkeypatch, capsys)
    assert rc == 0
    rows = {int(ln.split()[0]): ln for ln in out.splitlines()[1:]}
    assert set(rows) == {1, 2, 3, 4, 5, 6, 7}
    assert "extended" in rows[4]
    for n in (5, 6, 7):
        assert "logical" in rows[n] and "EBR at" in rows[n]
    assert "games" in rows[3] and "games (2nd)" in rows[7]
    assert "games" not in rows[5] and "games" not in rows[6]


def test_rootfs_file_reads_through_debugfs_and_treats_empty_as_absent(
        parts, monkeypatch):
    """`debugfs -R cat` exits 0 for a missing file (the complaint goes to
    stderr), so an empty answer is the only "not there" there is."""
    calls = []

    class R:
        def __init__(self, stdout):
            self.returncode, self.stdout = 0, stdout

    def fake_run(argv, **kw):
        calls.append(argv)
        cmd = argv[2]
        if cmd == "cat /usr/local/codeselect/images.conf":
            return R(b"image=/dev/mmcblk0p3|STERN STOCK|1.59.0\n")
        return R(b"")

    monkeypatch.setattr(parts.mod.subprocess, "run", fake_run)
    text = parts.mod.rootfs_file(parts.img, "/usr/local/codeselect/images.conf")
    assert text == "image=/dev/mmcblk0p3|STERN STOCK|1.59.0\n"
    assert calls[-1][-1] == "%s?offset=%d" % (parts.img, P2 * SECTOR), \
        "read out of the ROOTFS partition, not the games one"
    assert parts.mod.rootfs_file(parts.img, "/nope") is None


# ==========================================================================
# run_game.sh: where the selector runs, and that the exec lines did not move
# ==========================================================================

#: The two exec lines, byte for byte as they were before item 90. Copied from
#: the file rather than pattern-matched: the whole point is that they are
#: unchanged, and a looser test could be satisfied by a changed line.
EXEC_PIVOT = "        exec /.padqemu/game ./game </dev/null >/dump/game.out 2>&1"
EXEC_CHROOT = ('exec chroot "$R" /bin/sh -c \\\n'
               '  "cd /games/$GAME && LD_PRELOAD=${PAD_TRACE_SO:+$PAD_TRACE_SO:}'
               '/lib/hwshim.so PAD_AUDIO_OUT=/dump/audio.raw PAD_SEGV_REPORT=1 '
               'exec ./game"')


def test_the_two_exec_lines_are_unchanged():
    text = _read("run_game.sh")
    assert EXEC_PIVOT in text
    assert EXEC_CHROOT in text
    assert text.count("exec ./game") == 1 and text.count("./game </dev/null") == 1


def test_the_selector_runs_after_the_device_binds_and_before_the_pivot():
    """After every mount the game will see, before `cd "$R"` - so the pivot
    path and the chroot path run it identically and neither exec line has to
    change. The -invert masking moved BELOW it, so it masks the CHOSEN image's
    boot_display_cmd."""
    text = _read("run_game.sh")
    sel = _line_of(text, "chroot \"$R\" /usr/local/codeselect/codeselect")
    binds = _line_of(text, 'mount --bind "$NODEBUS_PTY" "$R/dev/ttymxc1"')
    cd = _line_exactly(text, 'cd "$R"')
    bdc = _line_of(text, 'BDC="$R/games/data/boot_display_cmd"')
    pivot = _line_of(text, "if $PIVOTROOT . oldroot")
    assert binds < sel < bdc < cd < pivot, (binds, sel, bdc, cd, pivot)


def test_the_selector_runs_without_the_shim_and_with_stdin_closed():
    """hwshim.so serves the cabinet word from the GAME's heap table and hooks
    the device nodes - not a menu program's shape. And `bash -s` reads its own
    script from stdin, so a child that reads stdin eats the rest of it."""
    text = _read("run_game.sh")
    line = next(ln for ln in text.splitlines()
                if 'chroot "$R" /usr/local/codeselect/codeselect' in ln)
    assert "LD_PRELOAD" not in line
    assert "</dev/null" in line
    assert "--input padsw" in line
    assert '--out "$PAD_SELECT_CHOICE"' in line, "the choice path is padpath.sh's, once"
    assert "--conf /dump/codeselect.conf" in line
    assert "--log /dump/codeselect.log" in line
    assert '--timeout "${PAD_SELECT_TIMEOUT:-30}"' in line


def test_everything_new_in_run_game_is_gated_on_pad_select():
    """A plain run must be byte-for-byte the launch it always was."""
    code = _code(_read("run_game.sh"))
    # The outer preparation sits under the PAD_SELECT test...
    outer = code[code.index('if [ -n "${PAD_SELECT:-}" ]; then'):]
    outer = outer[:outer.index("elif [ -n \"${PAD_GAME_DIR:-}\" ]")]
    for needed in ("parts.py\" --list-games", "cardmount.sh\" \"$PAD_CARD\" --part",
                   "codeselect.conf", "--rootfs-file /usr/local/codeselect/images.conf",
                   "timeout=${PAD_SELECT_TIMEOUT:-30}"):
        assert needed in outer, needed
    # ...and the INNER block under the list it produced, which is empty
    # otherwise - so nothing else reads it.
    inner = code[code.index('if [ -n "$SEL_DIRS" ]; then'):]
    inner = inner[:inner.index('BDC="$R/games/data/boot_display_cmd"')]
    assert "codeselect" in inner and "mount --bind" in inner
    assert "[select] chose" in inner and "[select] fallback" in inner
    assert '"${SEL_DIRS:-}" <<\'INNER\'' in code, "the list rides into the namespace as one argument"


def test_a_pad_select_run_refuses_rather_than_silently_booting_the_primary():
    code = _code(_read("run_game.sh"))
    block = code[code.index('if [ ! -x "$PAD_SELECT_BIN" ]'):]
    block = block[:block.index("fi")]
    assert "exit 1" in block and "not built" in block


def test_the_choice_file_is_defined_once_and_reused():
    """One spelling of /dump/select.choice: padpath.sh's. The selector is told
    it and run_game.sh reads it back; two spellings is how a choice goes
    unread."""
    defs = []
    for name in sorted(os.listdir(RIG)):
        if name.endswith(".sh"):
            for n, ln in enumerate(_read(name).splitlines(), 1):
                if re.match(r"\s*PAD_SELECT_CHOICE=", ln):
                    defs.append("%s:%d" % (name, n))
    assert defs == ["padpath.sh:%d" % _line_of(_read("padpath.sh"), "PAD_SELECT_CHOICE=")], defs
    assert "export PAD_SELECT_CHOICE" in _read("padpath.sh")
    run = _code(_read("run_game.sh"))
    assert "/dump/select.choice" not in run
    assert '"$R$PAD_SELECT_CHOICE"' in run


# ==========================================================================
# watch.sh: the flag, the wait, the feed, the teardown
# ==========================================================================

def test_the_selecting_flag_exists_only_on_a_pad_select_run():
    text = _read("watch.sh")
    assert ('if [ -n "${PAD_SELECT:-}" ]; then' in text)
    raise_ = _line_of(text, ': > "$ROOT/dump/selecting"')
    launch = _line_of(text, 'bash "$RIG/run_game.sh" > "$LOG" 2>&1 &')
    assert raise_ < launch, "raised BEFORE the launch, or the menu can be up unflagged"
    # ...and torn down on a plain run, so a stale flag cannot leak forward.
    block = text.split("\n")[raise_ - 8: raise_ + 3]
    assert any('rm -f "$ROOT/dump/selecting"' in ln for ln in block)
    assert any('if [ -n "${PAD_SELECT:-}" ]; then' in ln for ln in block)


def test_the_start_wait_and_the_poll_loop_ride_the_flag_under_a_guard():
    text = _read("watch.sh")
    code = _code(text)
    # Every reference to the flag outside its creation is under PAD_SELECT.
    lines = code.split("\n")
    guarded = 0
    for i, ln in enumerate(lines):
        if "dump/selecting" not in ln:
            continue
        window = "\n".join(lines[max(0, i - 40): i + 1])
        assert 'PAD_SELECT' in window, "unguarded use of the flag: %s" % ln.strip()
        guarded += 1
    assert guarded >= 6
    # The start wait clears it on the GAME's comm, not the selector's, and
    # gives up when run_game.sh is gone - not by waiting out the clock.
    wait = code[code.index("boot selector: waiting for the choice"):]
    wait = wait[:wait.index("waiting for the game to start")]
    assert "pgrep -x game" in wait and 'kill -0 "$GAMEPG"' in wait
    assert "SEL_WAIT" in wait
    # The poll loop: the same shape as the reloading flag, checked BEFORE the
    # guest-exit test.
    poll = _line_of(text, 'if [ -n "${PAD_SELECT:-}" ] && [ -f "$ROOT/dump/selecting" ]')
    exit_test = [n for n, ln in enumerate(text.split("\n"), 1)
                 if "if ! pad_guest_up; then" in ln]
    assert any(n > poll for n in exit_test)
    assert _line_of(text, 'if [ -f "$ROOT/dump/reloading" ]') < poll < max(exit_test)
    # The original 60 s wait is still there, untouched.
    assert "for i in $(seq 1 240); do" in code


def test_the_bound_comes_from_the_countdown_and_zero_means_for_ever():
    code = _code(_read("watch.sh"))
    assert "SEL_TO=${PAD_SELECT_TIMEOUT:-30}" in code
    assert 'if [ "$SEL_TO" = 0 ]; then SEL_WAIT=0; else SEL_WAIT=$((SEL_TO + 60)); fi' in code


def test_autoattract_is_held_back_until_the_menu_has_chosen():
    """autoattract reads a quiet bus as a ready game and presses Service
    Back; the menu ignores it and the presses would be spent before Tech
    Alerts. The plain launch line stays verbatim in the other branch."""
    code = _code(_read("watch.sh"))
    plain = 'setsid_as_user bash "$S/autoattract.sh" "$LOG" > "$HOME/padauto.log" 2>&1 &'
    assert plain in code
    block = code[code.index('if [ "${PAD_AUTO_ATTRACT:-1}" != 0 ]; then'):]
    block = block[:block.index("PAD_SW_EXERCISE")]
    assert 'if [ -n "${PAD_SELECT:-}" ]; then' in block
    held = block[:block.index("else")]
    assert 'while [ -f "$f" ]' in held and 'exec bash "$@"' in held
    assert '"$ROOT/dump/selecting" "$SEL_WAIT"' in held
    assert "AUTOPG=$!" in held, "teardown kills what $! names"


def test_select_lines_reach_the_event_pane():
    code = _code(_read("watch.sh"))
    assert r"/\[vid\]|\[card\]|\[select\]/" in code


def test_the_extra_mounts_are_owned_and_torn_down_by_the_run():
    text = _read("watch.sh")
    code = _code(text)
    assert "CARD_MNTS=()" in code
    mount = code[code.index('if [ -n "${PAD_SELECT:-}" ]; then\n        SEL_PARTS='):]
    mount = mount[:mount.index("elif [ -n \"${PAD_GAME_DIR:-}\" ]")]
    assert 'cardmount.sh" "$PAD_CARD" --part "$_p"' in mount
    assert '*"already mounted"*) ;;' in mount, "only mounts THIS run created"
    assert 'CARD_MNTS+=("$(dirname "$_path")")' in mount
    # Declared ABOVE the block that fills it (the CARD_MNT lesson).
    assert _line_of(text, "CARD_MNTS=()") < _line_of(text, "CARD_MNTS+=(")
    tear = code[code.index("teardown() {"):code.index("trap 'teardown; exit 130'")]
    assert "unmount_card()" in tear
    assert 'unmount_card "$CARD_MNT"' in tear
    assert 'for _m in ${CARD_MNTS[@]+"${CARD_MNTS[@]}"}; do' in tear
    assert "pkill -9 -x codeselect" in tear


def test_watch_builds_the_selector_only_when_asked_and_fatally():
    code = _code(_read("watch.sh"))
    assert 'if [ -n "${PAD_SELECT:-}" ]; then pad_ensure_select || exit 1; fi' in code
    assert code.index("pad_ensure_bridge || exit 1") < code.index("pad_ensure_select")


def test_the_savestate_guard_literals_keep_their_order():
    """test_spike2_savestate_guards.py pins these; a moved line there is a
    silent regression here, so the same order is asserted where the new
    code landed."""
    text = _read("watch.sh")
    gate = _line_of(text, "! pad_can_pivot")
    assert gate < _line_of(text, "[watch] cfg argv=")
    assert gate < _line_of(text, 'PAD_SAVESTATES:-${PAD_PIVOT:-0}')
    assert gate < _line_of(text, 'PAD_PIVOT="${PAD_PIVOT:-}"')
    assert "unset PAD_PIVOT" in text


# ==========================================================================
# the same-day rule: counted, killed, and built from one list
# ==========================================================================

def test_alive_counts_the_selector_and_killgame_kills_it():
    alive = _read("alive.sh")
    assert "SEL=$(n -x codeselect)" in alive
    procs = next(ln for ln in alive.splitlines() if ln.startswith("PROCS=$(("))
    assert "SEL" in procs, "counted in --procs/--total, not just printed"
    assert "codeselect" in alive[alive.index("--- what is still up ---"):]
    kill = _code(_read("killgame.sh"))
    assert "pkill -9 -x codeselect" in kill
    assert kill.index("pkill -9 -x codeselect") < kill.index("pkill -9 -x padglhost")


def test_cardmount_part_mounts_beside_the_default_and_leaves_it_alone():
    code = _code(_read("cardmount.sh"))
    assert 'MNT="$CARDS/$LABEL"' in code, "the default mount dir is unchanged"
    assert 'MNT="$CARDS/$LABEL.p$PART"' in code
    assert 'if [ "$MODE" = "--part" ]; then' in code
    assert 'parts.py" --part "$PART" "$SRC"' in code
    # The eviction guard sees a live .pN mount, or the cache is pulled from
    # under it.
    assert "label_mounted()" in code
    room = code[code.index("cache_make_room() {"):code.index("cache_wait() {")]
    assert 'label_mounted "$vlabel" && continue' in room
    assert 'mountpoint -q "$CARDS/$vlabel"' not in room
    assert '"$CARDS/$1".p*' in code
    # --umount and --precache still work in their old positions.
    assert 'if [ "$MODE" = "--umount" ]; then' in code
    assert 'if [ "$MODE" = "--precache" ]; then' in code


def _srcs(var):
    m = re.search(r'^%s="([^"]*)"' % var, _read("padpath.sh"), re.M)
    assert m, "%s is not defined in padpath.sh" % var
    return m.group(1).split()


#: What the selector is built and installed from. The contract named the
#: first eight and the two vendored headers; the selector's own tree added
#: input.c/h, log.c/h, conf.h and the example conf that `make install` ships.
EXPECTED_SRCS = ["codeselect.c", "conf.c", "conf.h", "gfx.c", "gfx.h",
                 "egl_stern.c", "egl_stern.h", "input.c", "input.h",
                 "input_hw.c", "input_padsw.c", "log.c", "log.h",
                 "Makefile", "select.sh", "images.conf.example",
                 "third_party/stb_truetype.h", "third_party/stb_image.h"]


def test_padpath_lists_the_selector_sources_and_stamps_them():
    srcs = _srcs("PAD_SELECT_SRCS")
    assert srcs == ["codeselect/" + s for s in EXPECTED_SRCS]
    for must in ("codeselect/Makefile", "codeselect/select.sh"):
        assert must in srcs, "%s decides what runs; the digest has to see it" % must
    pp = _read("padpath.sh")
    assert "pad_select_hash()" in pp
    assert "PAD_SELECT_STAMP=$ROOT/usr/local/codeselect/codeselect.srcs" in pp
    assert "PAD_SELECT_BIN=$ROOT/usr/local/codeselect/codeselect" in pp
    assert "PAD_SELECT_CHOICE=/dump/select.choice" in pp


def test_buildselect_stages_the_list_and_calls_the_makefile_contract():
    text = _read("buildselect.sh")
    code = _code(text)
    assert "for f in $PAD_SELECT_SRCS; do" in code
    assert 'make -C "$STAGE/codeselect" ROOT="$R" BUILD="$STAGE/codeselect/build" DESTDIR="$R" install' in code
    assert 'pad_select_hash "$RIG" > "$PAD_SELECT_STAMP"' in code
    assert "set -e" in code, "a failed build must never lay a stamp down"
    assert code.index("make -C") < code.index("pad_select_hash")
    assert "-Werror=implicit-function-declaration" not in code, \
        "the compile line is the Makefile's, not this script's"


def test_ensurebuild_gates_the_selector_like_the_shim():
    eb = _read("ensurebuild.sh")
    body = eb[eb.index("pad_ensure_select() {"):]
    body = body[:body.index("\n}")]
    assert "buildselect.sh" in body
    assert "_pad_run_live" in body, "never rebuilt under a live run"
    assert "_pad_stale" in body and "$PAD_SELECT_STAMP" in body
    assert "pad_select_hash" in body
    assert "arm-linux-gnueabihf-gcc" in body
    # MISSING is fatal (return 1 after a failed build), STALE is not.
    missing = body[body.index('if [ ! -x "$bin" ]; then'):body.index("_pad_stale")]
    assert "return 1" in missing
    stale = body[body.index("_pad_stale"):]
    assert "return 1" not in stale


def _selector_tree():
    """The selector's sources, or a skip while they are not in this checkout
    (they are written by the selector agent, beside this rig work)."""
    mk = os.path.join(RIG, "codeselect", "Makefile")
    if not os.path.isfile(mk):
        pytest.skip("codeselect/Makefile is not in this checkout yet - the "
                    "selector's sources are written by the selector agent")
    with open(mk, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def test_every_listed_selector_source_is_there_and_reaches_the_makefile():
    """The alsastub.c lesson for the selector, in both directions.

    A .c on the list that the Makefile never compiles is an edit that is
    digested and never built. A header is pulled in by the compiler, so it
    only has to be a make PREREQUISITE when some source #includes it - a
    vendored header nobody includes (stb_image.h today) is digested for the
    day it is, and make rightly ignores it until then."""
    mk = _selector_tree()
    srcs = _srcs("PAD_SELECT_SRCS")
    absent = [s for s in srcs if not os.path.isfile(os.path.join(RIG, s))]
    assert not absent, "PAD_SELECT_SRCS names files that are not there: %s" % absent
    c_missing = [s for s in srcs
                 if s.endswith(".c") and os.path.basename(s) not in mk]
    assert not c_missing, "PAD_SELECT_SRCS names %s and the Makefile never compiles them" % c_missing
    included = ""
    for s in srcs:
        if s.endswith(".c"):
            with open(os.path.join(RIG, s), encoding="utf-8", errors="replace") as fh:
                included += fh.read()
    h_missing = [s for s in srcs
                 if s.endswith(".h") and os.path.basename(s) in included
                 and os.path.basename(s) not in mk]
    assert not h_missing, ("%s are #included but not make prerequisites, so an "
                           "edit to them is digested and never rebuilt" % h_missing)


def test_every_source_the_makefile_compiles_or_installs_is_on_the_list():
    """THE OTHER DIRECTION, and the one that bites first: buildselect.sh
    stages ONLY the list, so a source the Makefile needs and the list lacks
    is `No such file` inside make - after the digest said everything was
    current."""
    mk = _selector_tree()
    listed = {os.path.basename(s) for s in _srcs("PAD_SELECT_SRCS")}
    needed = set()
    for var in ("SRCS", "HDRS"):
        m = re.search(r"^%s\s*=\s*(.*)$" % var, mk, re.M)
        assert m, "the Makefile no longer defines %s" % var
        needed.update(m.group(1).split())
    # Files `install` copies by name, and headers named as explicit
    # prerequisites (third_party/...).
    needed.update(re.findall(r"install -m \d+ ([A-Za-z0-9_.]+) ", mk))
    needed.update(os.path.basename(p) for p in
                  re.findall(r"third_party/[A-Za-z0-9_.]+", mk))
    missing = sorted(needed - listed)
    assert not missing, "the Makefile needs %s and PAD_SELECT_SRCS does not stage them" % missing


def test_the_readme_names_the_knobs_and_the_files():
    text = _read("README.md")
    sec = text[text.index("## Boot selector"):text.index("## Titles")]
    for word in ("PAD_SELECT=1", "PAD_SELECT_TIMEOUT", "PAD_CARD_CACHE=0",
                 "select.choice", "codeselect.log", "codeselect.conf",
                 "codeselect/DESIGN.md", "buildselect.sh"):
        assert word in sec, word


# ---- the video host follows the CHOSEN partition (dump/vidroot) ------------
# padvidhost runs outside the guest's mount namespace and resolves the game's
# relative clip paths against PAD_VID_ROOT, which watch.sh exports from the
# PRIMARY games partition before the menu is up. Run 2 of item 90 (2026-09-01)
# booted the 1987 image's game while padvidhost served the stock image's
# clips. run_game.sh now publishes the chosen directory in dump/vidroot after a
# successful bind; the host reads it per clip; plain runs clear it.


def test_run_game_publishes_vidroot_only_after_a_successful_bind():
    text = _read("run_game.sh")
    bind = text.index('elif mount --bind "$SEL_DIR" "$R/games/$GAME"; then')
    publish = text.index('> "$R/dump/vidroot"', bind)
    nxt = text.index("    else", bind)          # the fallback branch that follows          # the next elif/else branch
    assert bind < publish < nxt, "vidroot is written inside the bound-over branch"
    assert 'rm -f "$R/dump/vidroot"' in text, "a stale override is cleared before a new choice"


def test_watch_clears_vidroot_on_a_plain_run():
    text = _read("watch.sh")
    assert 'rm -f "$ROOT/dump/selecting" "$ROOT/dump/vidroot"' in text


def test_padvidhost_reads_the_override_per_clip():
    text = _read("padvidhost.py")
    assert 'os.path.join(padpath.root(), "dump", "vidroot")' in text
    assert "def host_root():" in text
    body = text[text.index("def host_path(p):"):]
    assert "root = host_root()" in body
    assert "os.path.join(HOST_ROOT, p)" not in body, "host_path must not bypass the override"
