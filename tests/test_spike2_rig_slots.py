"""Rig slots: several Spike 2 emulator rigs on one PC (docs/plans/rig_slots.md).

PAD_SLOT=N gives a run its own rig - an overlay rootfs, its own renderer
build, logs, card mountpoints and audio port - and every pgrep/pkill in the
run path asks only about that slot. Slot 0 (unset) is the ordinary rig and
must not change at all. The board (riglock.sh) records who holds which slot,
and every window a run opens says which rig and whose run it is.

These run padpath.sh / riglock.sh under bash with a scratch home and a scratch
board, so they touch nothing real. The /proc cases skip where there is no
/proc (Git Bash).
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BASH = shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present"),
    pytest.mark.skipif(not BASH, reason="no bash"),
]


def _src(name):
    with open(os.path.join(RIG, name), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _sh(script, env=None, timeout=60):
    """Run `script` in bash with the rig dir as $R; (rc, stdout, stderr)."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("PAD_")}
    e.update(env or {})
    rig = RIG.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", rig):          # Git Bash spells C:/ as /c/
        rig = "/" + rig[0].lower() + rig[2:]
    out = subprocess.run([BASH, "-c", 'R="%s"\n%s' % (rig, script)],
                         capture_output=True, text=True, timeout=timeout, env=e)
    return out.returncode, out.stdout, out.stderr


def _vars(script_env, names):
    """Source padpath.sh with `script_env` and print `names`, one per line."""
    body = '. "$R/padpath.sh"\n' + "".join(
        'printf "%%s=%%s\\n" %s "${%s:-}"\n' % (n, n) for n in names)
    rc, out, err = _sh(body, script_env)
    assert rc == 0, err
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


PATHS = ["PAD_SLOT", "PAD_SLOTDIR", "PAD_ROOT", "PAD_TABLES", "PAD_STAGE",
         "PAD_LOGDIR", "PAD_CARDS", "PAD_GLHOST_BIN", "PAD_GLHOST_STAMP",
         "PAD_AUDIO_PORT", "PAD_BASE_ROOT"]


# --------------------------------------------------------------------------
# PATHS: slot 0 is the rig as it always was; slot N is its own
# --------------------------------------------------------------------------

def test_slot_zero_is_the_ordinary_rig_unchanged():
    v = _vars({"PAD_HOME": "/home/pad"}, PATHS)
    assert v["PAD_SLOT"] == "0"
    assert v["PAD_SLOTDIR"] == ""
    assert v["PAD_ROOT"] == "/home/pad/spike2root"
    assert v["PAD_TABLES"] == "/home/pad/spike2root/dump/tables"
    assert v["PAD_STAGE"] == "/home/pad/emusrc"
    assert v["PAD_LOGDIR"] == "/home/pad"
    assert v["PAD_CARDS"] == "/home/pad/card"
    assert v["PAD_GLHOST_BIN"] == "/home/pad/padglhost"
    assert v["PAD_GLHOST_STAMP"] == "/home/pad/padglhost.srcs"
    # 45997 stays playaudio.sh's own default: slot 0 exports no port at all.
    assert v["PAD_AUDIO_PORT"] == ""


def test_slot_n_has_its_own_everything():
    v = _vars({"PAD_HOME": "/home/pad", "PAD_SLOT": "2"}, PATHS)
    d = "/home/pad/padslots/2"
    assert v["PAD_SLOTDIR"] == d
    assert v["PAD_ROOT"] == d + "/root"
    assert v["PAD_TABLES"] == d + "/root/dump/tables"
    assert v["PAD_STAGE"] == d + "/emusrc"
    assert v["PAD_LOGDIR"] == d
    assert v["PAD_CARDS"] == d + "/card"
    assert v["PAD_GLHOST_BIN"] == d + "/padglhost"
    assert v["PAD_AUDIO_PORT"] == "45999"
    # The overlay's lower layer is slot 0's rootfs.
    assert v["PAD_BASE_ROOT"] == "/home/pad/spike2root"


def test_a_slot_never_boots_from_an_inherited_slot_zero_root():
    """A slot run that inherited slot 0's exported paths would build into and
    boot from the SHARED rootfs while calling itself slot N - silently."""
    v = _vars({"PAD_HOME": "/home/pad", "PAD_SLOT": "1",
               "PAD_PATHS_SLOT": "0",
               "PAD_ROOT": "/home/pad/spike2root",
               "PAD_TABLES": "/home/pad/spike2root/dump/tables",
               "PAD_LOGDIR": "/home/pad", "PAD_CARDS": "/home/pad/card",
               "PAD_STAGE": "/home/pad/emusrc"}, PATHS)
    assert v["PAD_ROOT"] == "/home/pad/padslots/1/root"
    assert v["PAD_TABLES"] == "/home/pad/padslots/1/root/dump/tables"
    assert v["PAD_LOGDIR"] == "/home/pad/padslots/1"
    assert v["PAD_CARDS"] == "/home/pad/padslots/1/card"
    assert v["PAD_STAGE"] == "/home/pad/padslots/1/emusrc"
    # ...even with no record of which slot the inherited root was for.
    v = _vars({"PAD_HOME": "/home/pad", "PAD_SLOT": "1",
               "PAD_ROOT": "/somewhere/else"}, ["PAD_ROOT"])
    assert v["PAD_ROOT"] == "/home/pad/padslots/1/root"


def test_a_slot_keeps_its_own_inherited_paths():
    """A run's own children re-source padpath.sh and must land where it did."""
    v = _vars({"PAD_HOME": "/home/pad", "PAD_SLOT": "3", "PAD_PATHS_SLOT": "3",
               "PAD_LOGDIR": "/tmp/mylogs"}, ["PAD_LOGDIR", "PAD_ROOT"])
    assert v["PAD_LOGDIR"] == "/tmp/mylogs"
    assert v["PAD_ROOT"] == "/home/pad/padslots/3/root"


def test_a_bad_slot_is_slot_zero_and_says_so():
    rc, out, err = _sh('. "$R/padpath.sh"; echo "$PAD_SLOT $PAD_ROOT"',
                       {"PAD_HOME": "/home/pad", "PAD_SLOT": "two"})
    assert out.strip() == "0 /home/pad/spike2root"
    assert "PAD_SLOT must be a number" in err


def test_python_agrees_with_the_shell(monkeypatch):
    sys.path.insert(0, RIG)
    try:
        import padpath
    finally:
        sys.path.remove(RIG)
    monkeypatch.setenv("PAD_SLOT", "2")
    monkeypatch.setenv("PAD_LABEL", "item/48")
    monkeypatch.delenv("PAD_ROOT", raising=False)
    monkeypatch.setenv("PAD_WSL_HOME", "/home/pad")
    assert padpath.slot() == 2
    assert padpath.title_tag() == "[rig 2: item/48]"
    if sys.platform != "win32":
        assert padpath.wsl_root() == "/home/pad/padslots/2/root"
    monkeypatch.setenv("PAD_SLOT", "0")
    monkeypatch.setenv("PAD_LABEL", "PAD-231")
    assert padpath.title_tag() == "[PAD-231]"
    monkeypatch.delenv("PAD_LABEL")
    assert padpath.title_tag() == ""
    monkeypatch.setenv("PAD_SLOT", "nonsense")
    assert padpath.slot() == 0


# --------------------------------------------------------------------------
# THE LABEL AND THE WINDOW TITLE
# --------------------------------------------------------------------------

def _label(env, git_head=None, gitfile=None):
    """pad_label / pad_title_tag with the rig moved into a scratch checkout
    whose .git says what we want, so the real branch cannot leak in."""
    setup = r'''
t=$(mktemp -d) || exit 1
mkdir -p "$t/repo/tools/spike2_emu" "$t/board"
cp "$R"/padpath.sh "$R"/padslot.sh "$t/repo/tools/spike2_emu/"
'''
    if git_head:
        setup += 'mkdir -p "$t/repo/.git"; printf "%%s\\n" "%s" > "$t/repo/.git/HEAD"\n' % git_head
    if gitfile:
        setup += ('mkdir -p "$t/gd"; printf "%%s\\n" "%s" > "$t/gd/HEAD"\n'
                  'printf "gitdir: ../gd\\n" > "$t/repo/.git"\n' % gitfile)
    setup += r'''
export PAD_BOARD="$t/board"
. "$t/repo/tools/spike2_emu/padpath.sh"
printf 'label=%s\ntag=%s\n' "$(pad_label)" "$(pad_title_tag)"
rm -rf "$t"
'''
    rc, out, err = _sh(setup, dict({"PAD_HOME": "/home/pad"}, **env))
    assert rc == 0, err
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_the_title_tag_names_the_rig_and_the_run():
    v = _label({"PAD_SLOT": "2", "PAD_LABEL": "item/48"})
    assert v["tag"] == "[rig 2: item/48]"
    v = _label({"PAD_SLOT": "2"}, git_head="ref: refs/heads/main")
    assert v["tag"] == "[rig 2]"


def test_main_in_rig_zero_has_no_tag_at_all():
    """David's own runs from main: titles exactly as before slots."""
    v = _label({}, git_head="ref: refs/heads/main")
    assert v["label"] == "" and v["tag"] == ""


def test_the_branch_names_the_run_and_a_ticket_branch_is_its_ticket():
    assert _label({}, git_head="ref: refs/heads/item/48")["tag"] == "[item/48]"
    assert _label({}, git_head="ref: refs/heads/ticket/PAD-7")["label"] == "PAD-7"
    # A worktree's .git is a FILE pointing at the real gitdir.
    assert _label({}, gitfile="ref: refs/heads/feature/x")["label"] == "feature/x"


def test_ticket_beats_branch_and_explicit_label_beats_everything():
    assert _label({"PAD_TICKET": "PAD-9"},
                  git_head="ref: refs/heads/item/48")["label"] == "PAD-9"
    assert _label({"PAD_TICKET": "PAD-9", "PAD_LABEL": "mine"},
                  git_head="ref: refs/heads/item/48")["label"] == "mine"


def test_the_label_is_title_safe():
    v = _label({"PAD_SLOT": "1", "PAD_LABEL": 'a"b;$(rm)\u00e9' + "x" * 80})
    assert '"' not in v["tag"] and ";" not in v["tag"] and "$" not in v["tag"]
    assert len(v["label"]) <= 40


def test_every_renderer_window_carries_the_tag():
    c = _src("padglhost.c")
    assert 'getenv("PAD_TITLE_TAG")' in c
    # the game window, the second display and the Controls legend
    assert c.count("title_tag()") >= 3
    assert '"%sControls - Spike 2 emulator", title_tag()' in c


def test_the_playfield_title_tag_is_at_the_front():
    p = _src("playfield.py")
    assert "WINDOW_TITLE = ((padpath.title_tag()" in p
    assert '"rig": {"slot": padpath.slot(), "label": padpath.label()}' in p


# --------------------------------------------------------------------------
# THE BOARD: riglock.sh
# --------------------------------------------------------------------------

_BOARD = r'''
t=$(mktemp -d) || exit 1
export PAD_BOARD="$t/board" PAD_HOME="$t/home" PAD_SLOTS_MAX=3
mkdir -p "$PAD_HOME" "$t/rig"
# riglock's own copy with an alive.sh that sees no processes: the real one
# reads /proc, and on a dev box with other sessions' rigs up "a run is still
# up" is the right answer there, not what these tests are about.
cp "$R/riglock.sh" "$R/padpath.sh" "$R/padslot.sh" "$t/rig/"
printf 'echo 0\n' > "$t/rig/alive.sh"
L() { bash "$t/rig/riglock.sh" "$@"; }
'''


def test_take_any_gives_distinct_slots_and_refuses_when_full():
    rc, out, err = _sh(_BOARD + r'''
L take --any item/48 godzilla run 2>/dev/null
L take --any PAD-231 build 2>/dev/null
L take --any item/50 app 2>/dev/null
L take --any item/51 one too many 2>/dev/null || echo "full rc=$?"
rm -rf "$t"
''')
    assert out.splitlines() == ["slot=1", "slot=2", "slot=3", "full rc=1"]


def test_a_held_slot_cannot_be_taken_and_only_its_holder_releases_it():
    rc, out, err = _sh(_BOARD + r'''
L take --slot 2 item/48 godzilla run 2>/dev/null
L take --slot 2 PAD-231 me too 2>/dev/null || echo "held"
L release 2 PAD-231 2>/dev/null || echo "not yours"
L release 2 item/48
L take --slot 2 PAD-231 now mine 2>/dev/null
rm -rf "$t"
''')
    assert out.splitlines() == ["slot=2", "held", "not yours",
                                "released slot 2", "slot=2"]


def test_the_lock_record_is_json_the_app_and_dashboard_can_read():
    import json
    rc, out, err = _sh(_BOARD + r'''
L take --slot 1 'item/48' 'godzilla "run", now' >/dev/null 2>&1
cat "$PAD_BOARD/slot-1.lock"
L list --json
rm -rf "$t"
''')
    lines = out.splitlines()
    rec = json.loads(lines[0])
    assert rec["slot"] == 1 and rec["who"] == "item/48"
    assert rec["what"] == "godzilla run, now"     # quotes stripped, not escaped
    assert isinstance(rec["taken"], int)
    board = json.loads(lines[1])
    assert board["max"] == 3
    assert [s["slot"] for s in board["slots"]] == [0, 1, 2, 3]
    assert board["slots"][1]["lock"]["who"] == "item/48"
    assert board["slots"][2]["lock"] is None


def test_note_keeps_the_holder_and_the_start_time():
    import json
    rc, out, err = _sh(_BOARD + r'''
L take --slot 1 item/48 build >/dev/null 2>&1
a=$(cat "$PAD_BOARD/slot-1.lock")
L note 1 godzilla run
b=$(cat "$PAD_BOARD/slot-1.lock")
printf '%s\n%s\n' "$a" "$b"
rm -rf "$t"
''')
    a, b = (json.loads(x) for x in out.splitlines())
    assert b["who"] == a["who"] == "item/48"
    assert b["taken"] == a["taken"]
    assert (a["what"], b["what"]) == ("build", "godzilla run")


def test_slot_zero_also_holds_the_pre_slot_lock_file():
    """Sessions that predate slots only know ~/.pad_rig_lock."""
    rc, out, err = _sh(_BOARD + r'''
L take --slot 0 item/48 base rebuild >/dev/null
cat "$PAD_HOME/.pad_rig_lock"
L release 0 item/48 >/dev/null
[ -e "$PAD_HOME/.pad_rig_lock" ] && echo still || echo gone
echo "item/9 old protocol" > "$PAD_HOME/.pad_rig_lock"
L take --slot 0 item/48 again 2>/dev/null || echo "refused"
L list | sed -n 2p
rm -rf "$t"
''')
    lines = out.splitlines()
    assert lines[0] == "item/48 base rebuild"
    assert lines[1] == "gone"
    assert lines[2] == "refused"
    assert "item/9" in lines[3]


def test_release_is_refused_while_the_board_says_a_run_is_up():
    rc, out, err = _sh(_BOARD + r'''
L take --slot 1 item/48 run >/dev/null 2>&1
printf '{"slot":1,"game":"godzilla_pro","started":%s}\n' "$(date +%s)" > "$PAD_BOARD/slot-1.run"
L release 1 item/48 2>/dev/null || echo "refused"
L list | sed -n 3p
L release 1 item/48 --force
rm -rf "$t"
''')
    lines = out.splitlines()
    assert lines[0] == "refused"
    assert "godzilla_pro up" in lines[1]
    assert lines[2] == "released slot 1"


def test_a_run_record_that_stopped_beating_reads_as_stale():
    rc, out, err = _sh(_BOARD + r'''
mkdir -p "$PAD_BOARD"
printf '{"slot":2,"game":"turtles_pro","started":1}\n' > "$PAD_BOARD/slot-2.run"
touch -d '10 minutes ago' "$PAD_BOARD/slot-2.run" 2>/dev/null || touch -t 200001010000 "$PAD_BOARD/slot-2.run"
L list | sed -n 4p
rm -rf "$t"
''')
    assert "turtles_pro STALE" in out


# --------------------------------------------------------------------------
# A LOCK IS A LEASE (PAD-229): held only while the rig is in use
# --------------------------------------------------------------------------

_OLD = r'''old() { touch -d '10 minutes ago' "$1" 2>/dev/null || touch -t 200001010000 "$1"; }
'''


def test_an_unused_lock_is_cleared_by_the_next_look_at_the_board():
    """David 2026-09-27: the locks must clear THEMSELVES when not in use."""
    rc, out, err = _sh(_BOARD + _OLD + r'''
L take --slot 1 PAD-228 app >/dev/null 2>&1
L take --slot 2 PAD-226 build >/dev/null 2>&1
old "$PAD_BOARD/slot-1.lock"
L list | sed -n 3,4p
ls "$PAD_BOARD"
rm -rf "$t"
''')
    lines = out.splitlines()
    assert "(free)" in lines[0]
    assert "PAD-226" in lines[1] and re.search(r"idle [0-9]s", lines[1])
    assert "slot-1.lock" not in lines[2:] and "slot-2.lock" in lines[2:]
    assert "was PAD-228's" in err and "cleared" in err


def test_take_any_clears_a_lapsed_lock_and_takes_its_slot():
    rc, out, err = _sh(_BOARD + _OLD + r'''
L take --slot 1 PAD-228 app >/dev/null 2>&1
old "$PAD_BOARD/slot-1.lock"
L take --any PAD-231 first
L take --any PAD-232 second 2>/dev/null
L take --any PAD-233 third 2>/dev/null
L take --any PAD-234 none left 2>/dev/null || echo "full"
sed -n 's/.*"who":"\([^"]*\)".*/\1/p' "$PAD_BOARD/slot-1.lock"
ls "$PAD_BOARD" | grep -c seize
rm -rf "$t"
''')
    assert out.splitlines() == ["slot=1", "slot=2", "slot=3", "full", "PAD-231", "0"]
    assert "was PAD-228's" in err


def test_a_lapsed_lock_with_a_run_up_is_not_lapsed():
    rc, out, err = _sh(_BOARD + _OLD + r'''
L take --slot 1 PAD-228 run >/dev/null 2>&1
old "$PAD_BOARD/slot-1.lock"
printf '{"slot":1,"game":"godzilla_pro","started":1}\n' > "$PAD_BOARD/slot-1.run"
L take --slot 1 PAD-231 mine 2>/dev/null || echo "held"
rm -rf "$t"
''')
    assert out.strip() == "held"


def test_use_renews_mine_takes_a_free_or_lapsed_one_and_refuses_one_in_use():
    rc, out, err = _sh(_BOARD + _OLD + r'''
L use 1 PAD-231 run 2>/dev/null && echo "free: taken"
old "$PAD_BOARD/slot-1.lock"
L use 1 PAD-231 run 2>/dev/null && echo "mine: renewed"
L list | sed -n 3p | grep -Eq "idle [0-9]s" && echo "fresh again"
L use 1 PAD-232 stop 2>/dev/null || echo "in use: refused"
old "$PAD_BOARD/slot-1.lock"
L use 1 PAD-232 stop 2>/dev/null && echo "lapsed: taken"
rm -rf "$t"
''')
    assert out.splitlines() == ["free: taken", "mine: renewed", "fresh again",
                                "in use: refused", "lapsed: taken"]


def test_a_rig_command_on_someone_elses_slot_is_refused():
    """pad_slot_use - what watch.sh, killgame.sh and restorestate.sh say first.
    A session whose lease lapsed, and whose slot was taken meanwhile, must not
    Stop the new holder's run."""
    rc, out, err = _sh(_BOARD + r'''
L take --slot 2 PAD-226 godzilla run >/dev/null 2>&1
u() { PAD_SLOT=2 PAD_LABEL=$1 bash -c '. "$0/padpath.sh"; pad_slot_use stop' "$t/rig"; }
u PAD-231 2>/dev/null || echo "refused"
u PAD-226 && echo "mine"
PAD_SLOT=2 bash -c '. "$0/padpath.sh"; pad_slot_use stop && echo "nobody to name: as before"' "$t/rig"
PAD_NO_CLAIM=1 PAD_SLOT=2 PAD_LABEL=PAD-231 bash -c '. "$0/padpath.sh"; pad_slot_use && echo "opted out"' "$t/rig"
rm -rf "$t"
''')
    assert out.splitlines() == ["refused", "mine", "nobody to name: as before",
                                "opted out"]


def test_a_test_never_writes_the_real_board():
    """Under pytest with no board of its own, pad_slot_use does nothing - a
    ticket worktree's tests would otherwise take rigs on the developer's board."""
    rc, out, err = _sh(r'''
t=$(mktemp -d); mkdir -p "$t/rig"
cp "$R/riglock.sh" "$R/padpath.sh" "$R/padslot.sh" "$t/rig/"
printf 'echo "riglock ran"\n' > "$t/rig/riglock.sh"
PAD_HOME=$t PAD_SLOT=1 PAD_LABEL=PAD-231 PYTEST_CURRENT_TEST=x \
    bash -c '. "$0/padpath.sh"; pad_slot_use' "$t/rig"
echo "rc=$?"
rm -rf "$t"
''')
    assert out.splitlines() == ["rc=0"]


def test_the_scripts_that_act_on_a_slot_say_so_first():
    for name, what in (("watch.sh", "run"), ("killgame.sh", "stop"),
                       ("restorestate.sh", "restore")):
        s = open(os.path.join(RIG, name), encoding="utf-8").read()
        assert "pad_slot_use %s || exit 1" % what in s, name
    b = open(os.path.join(RIG, "rigbatch.sh"), encoding="utf-8").read()
    assert b.count('PAD_LABEL="$WHO" bash "$RIG/killgame.sh"') == 2


def test_the_board_lives_on_the_windows_side_of_a_windows_checkout():
    rc, out, err = _sh(r'''
RIG=/mnt/c/Users/pat/Documents/pad/tools/spike2_emu
. "$R/padslot.sh"
eval "$(sed -n '/^pad_board_dir()/,/^}/p' "$R/padpath.sh")"
pad_board_dir
RIG=/home/pat/pad/tools/spike2_emu PAD_HOME=/home/pat pad_board_dir
PAD_BOARD=/x/y pad_board_dir
''')
    assert out.splitlines() == ["/mnt/c/Users/pat/.pad-rig",
                                "/home/pat/.pad-rig", "/x/y"]


# --------------------------------------------------------------------------
# PROCESSES: every pgrep/pkill in the run path is slot-scoped
# --------------------------------------------------------------------------

#: Scripts on the run path. audioreset.sh is NOT here on purpose: it shuts
#: WSL down, which ends every slot's run, so its count is machine-wide.
_SCOPED = ["watch.sh", "killgame.sh", "alive.sh", "status.sh", "runbridge.sh",
           "loadgame.sh", "savegame.sh", "savestate.sh", "restorestate.sh",
           "slots.sh", "autoattract.sh", "swexercise.sh", "longplay.sh",
           "cardmount.sh", "ensurebuild.sh", "modes/gamecheck.sh"]


@pytest.mark.parametrize("name", _SCOPED)
def test_no_machine_wide_pgrep_or_pkill_on_the_run_path(name):
    bad = []
    for n, line in enumerate(_src(name).splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        if re.match(r"\s*echo\b", code):      # a message naming the tool
            continue
        if re.search(r"(?<![\w-])(pgrep|pkill)\b", code):
            bad.append("%s:%d: %s" % (name, n, line.strip()))
    assert not bad, "\n".join(bad)


def test_the_windows_backstops_match_only_this_slots_windows():
    for name in ("killgame.sh", "watch.sh"):
        s = _src(name)
        assert "-notlike '*--pad-slot=*'" in s, name
        assert "-like '*--pad-slot=$PAD_SLOT*'" in s, name
    k = _src("killgame.sh")
    assert "'* $_port *'" in k and "45997" in k


def test_a_slots_playfield_carries_its_marker():
    w = _src("watch.sh")
    assert 'PF_SLOTARG="--pad-slot=$PAD_SLOT"' in w
    assert w.count("$PF_STATES $PF_SLOTARG") == 2


def test_pause_freezes_only_this_slots_game():
    assert "pid_in_my_slot(pid)" in _src("padglhost.c")
    assert "padpath.in_my_slot(int(d))" in _src("pausekeep.py")


needs_proc = pytest.mark.skipif(not os.path.isdir("/proc/1"),
                                reason="no /proc here (Git Bash)")


@needs_proc
def test_pad_slot_of_reads_the_process_environment():
    rc, out, err = _sh(r'''
. "$R/padslot.sh"
env PAD_SLOT=3 sleep 30 & a=$!
env -u PAD_SLOT sleep 30 & b=$!
sleep 0.2
echo "$(pad_slot_of $a) $(pad_slot_of $b)"
kill $a $b; wait $a $b 2>/dev/null
echo "gone=$(pad_slot_of $a)"
''')
    assert out.splitlines() == ["3 0", "gone=-"], err


@needs_proc
def test_pad_pids_sees_only_its_own_slot():
    rc, out, err = _sh(r'''
. "$R/padslot.sh"
cp "$(command -v sleep)" /tmp/pss.$$ && S=/tmp/pss.$$
env PAD_SLOT=1 "$S" 30 & a=$!
env PAD_SLOT=2 "$S" 30 & b=$!
"$S" 30 & c=$!
sleep 0.2
n="pss.$$"
printf '1:%s 2:%s 0:%s\n' "$(PAD_SLOT=1 pad_pids -x "$n")" \
    "$(PAD_SLOT=2 pad_pids -x "$n")" "$(PAD_SLOT=0 pad_pids -x "$n")"
[ "$(PAD_SLOT=1 pad_pids -x "$n")" = "$a" ] && echo ok1
PAD_SLOT=2 pad_pkill -9 -x "$n"
sleep 0.2
kill -0 $a && kill -0 $c && ! kill -0 $b 2>/dev/null && echo "only slot 2 died"
kill $a $c; rm -f "$S"
''')
    assert "ok1" in out and "only slot 2 died" in out, out + err


def test_a_save_state_load_keeps_a_rigs_overlay_root():
    """restorestate.sh sweeps every mount out of the restore's namespace; a
    rig's rootfs IS a mount, and sweeping it left criu an empty root ("Can't
    stat mountpoint .../dev/shm", the first load in rig 1). Kept only when it
    is a mountpoint, so rig 0 - a plain directory - is unchanged."""
    s = _src("restorestate.sh")
    assert 'mountpoint -q "$R" 2>/dev/null && PAD_NS_KEEP_ROOT=$R' in s
    assert r'[ "\$mp" = "\$PAD_NS_KEEP_ROOT" ] && continue' in s


# --------------------------------------------------------------------------
# rigbatch.sh: one list of builds, spread across several rigs
# --------------------------------------------------------------------------

_BATCH = r'''
t=$(mktemp -d) || exit 1
mkdir -p "$t/rig" "$t/home" "$t/board"
cp "$R"/padpath.sh "$R"/padslot.sh "$R"/riglock.sh "$R"/rigbatch.sh "$t/rig/"
# STUB rigs: nothing here may ever reach a real one on this machine
printf '#!/bin/bash\necho 0\n' > "$t/rig/alive.sh"
printf '#!/bin/bash\n:\n' > "$t/rig/killgame.sh"
cat > "$t/job.sh" <<'JOB'
#!/bin/bash
# a job: note which rig ran which build, fail the one named "bad"
echo "$PAD_SLOT $1 $2 $FLAVOUR" >> "$JOBLOG"
sleep 0.3
[ "$1" = bad ] && { echo "VERDICT $1 fail 1s state=booting"; exit 1; }
echo "VERDICT $1 pass 1s state=attract"
JOB
printf 'a|/cards/a.raw|FLAVOUR=x\n# comment\n\nb|/cards/b.raw|\nbad|/cards/bad.raw|\nc|/cards/c.raw|\n' > "$t/l.list"
export PAD_HOME="$t/home" PAD_BOARD="$t/board" PAD_SLOTS_MAX=3 JOBLOG="$t/jobs.txt"
export PAD_RIGBATCH_ASSUME_MOUNTED=1
bash "$t/rig/rigbatch.sh" -n 2 --who PAD-9 --out "$t/out" "$t/l.list" -- bash "$t/job.sh" > "$t/stdout" 2>&1
echo "rc=$?"
echo "--- jobs"; sort "$t/jobs.txt"
echo "--- results"; cut -f1,3 "$t/out/results.tsv" | sort
echo "--- locks left"; ls "$t/board"
echo "--- tail"; tail -3 "$t/out/progress.txt"
rm -rf "$t"
'''


@needs_proc
def test_rigbatch_spreads_a_list_across_rigs_and_frees_them():
    """Linux only, like the rig: rigbatch's workers need setsid and flock."""
    rc, out, err = _sh(_BATCH, {"PAD_HOME": "/nonexistent"}, timeout=120)
    assert "rc=1" in out, out + err                     # one build failed
    body = out.split("--- jobs")[1].split("--- results")[0].strip().splitlines()
    rigs = {ln.split()[0] for ln in body}
    keys = sorted(ln.split()[1] for ln in body)
    assert keys == ["a", "b", "bad", "c"]               # every build once
    assert rigs == {"1", "2"}                           # both rigs worked
    assert any(ln.split()[1:] == ["a", "/cards/a.raw", "x"] for ln in body)
    res = out.split("--- results")[1].split("--- locks left")[0].split()
    assert res == ["a", "pass", "b", "pass", "bad", "fail", "c", "pass"]
    assert out.split("--- locks left")[1].split("--- tail")[0].strip() == ""
    assert "ALL DONE: 3/4 pass" in out and "FAIL VERDICT bad fail" in out


_STAGED = r'''
t=$(mktemp -d) || exit 1
mkdir -p "$t/rig" "$t/home" "$t/board" "$t/slowdisk" "$t/stage"
cp "$R"/padpath.sh "$R"/padslot.sh "$R"/riglock.sh "$R"/rigbatch.sh "$R"/cardstage.sh "$t/rig/"
printf '#!/bin/bash\necho 0\n' > "$t/rig/alive.sh"
printf '#!/bin/bash\n:\n' > "$t/rig/killgame.sh"
for c in a b c; do head -c 2048 /dev/urandom > "$t/slowdisk/$c.raw"; done
cat > "$t/job.sh" <<'JOB'
#!/bin/bash
echo "$1 $2" >> "$JOBLOG"
cmp -s "$2" "$SLOW/$(basename "$2")" || { echo "VERDICT $1 fail not a copy"; exit 1; }
echo "VERDICT $1 pass"
JOB
printf 'a|%s|\nb|%s|\nnone|%s|\nc|%s|\n' "$t/slowdisk/a.raw" "$t/slowdisk/b.raw" \
    "$t/slowdisk/missing.raw" "$t/slowdisk/c.raw" > "$t/l.list"
export PAD_HOME="$t/home" PAD_BOARD="$t/board" PAD_SLOTS_MAX=3 JOBLOG="$t/jobs.txt"
export PAD_RIGBATCH_ASSUME_MOUNTED=1 PAD_STAGE_COPY=cp SLOW="$t/slowdisk" PAD_STAGE_SPARE_GB=0
bash "$t/rig/rigbatch.sh" -n 2 --who PAD-9 --out "$t/out" --stage "$t/stage" "$t/l.list" \
    -- bash "$t/job.sh" > "$t/stdout" 2>&1
echo "rc=$?"
echo "--- jobs"; sed "s#$t#T#g" "$t/jobs.txt" | sort
echo "--- results"; cut -f1,3 "$t/out/results.tsv" | sort
echo "--- staged"; ls "$t/stage" | sort
echo "--- again"
bash "$t/rig/rigbatch.sh" -n 2 --who PAD-9 --out "$t/out2" --stage "$t/stage" "$t/l.list" \
    -- bash "$t/job.sh" > /dev/null 2>&1
grep -c ' reuse ' "$t/out2/stage.log"
rm -rf "$t"
'''


@needs_proc
def test_a_batchs_end_leaves_other_batches_copies_in_flight():
    """PAD-420: several batches stage into one folder at once; each copies into a folder of its own under .inflight
    (named from its out dir) and its end removes only that one. The shared .partial emptied at one batch's end had
    deleted another batch's card mid-copy (that build then failed staging)."""
    cs = open(os.path.join(RIG, "cardstage.sh"), encoding="utf-8").read()
    rb = open(os.path.join(RIG, "rigbatch.sh"), encoding="utf-8").read()
    own = '$(printf %s "$OUT" | md5sum | cut -c1-12)'
    assert 'P=$STAGE/.inflight/%s' % own in cs and 'copy "$card" "$P"' in cs and '"$STAGE/.partial"' not in cs
    assert 'rm -rf "$STAGE/.inflight/%s"' % own in rb and 'rm -rf "$STAGE/.partial"\n' not in rb


def test_rigbatch_boots_staged_copies_and_reuses_them():
    """cardstage.sh: every rig boots a copy staged off the slow disk; a card
    that cannot be staged fails its build (not the batch); a second sweep
    reuses what the first staged."""
    rc, out, err = _sh(_STAGED, {"PAD_HOME": "/nonexistent"}, timeout=180)
    assert "rc=1" in out, out + err
    jobs = out.split("--- jobs")[1].split("--- results")[0].split()
    assert jobs == ["a", "T/stage/a.raw", "b", "T/stage/b.raw", "c", "T/stage/c.raw"]
    res = out.split("--- results")[1].split("--- staged")[0].split()
    assert res == ["a", "pass", "b", "pass", "c", "pass", "none", "fail"]
    staged = out.split("--- staged")[1].split("--- again")[0].split()
    assert staged == ["a.raw", "a.raw.src", "b.raw", "b.raw.src", "c.raw", "c.raw.src"]
    assert out.split("--- again")[1].strip() == "3"
