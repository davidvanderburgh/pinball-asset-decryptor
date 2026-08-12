"""Is there a display to put the game window on, and does the run SAY so?

THE FAULT, reported 2026-08-11: the virtual playfield window opens, it says
"emulator up", the guest is really running - and there is no game window
anywhere.  From outside, that run looks perfectly healthy: watch.sh printed
nothing unusual, because the only record of it was one line inside
``~/padglhost.log``, which nothing forwards and nobody reads.

``[ -z "$DISPLAY" ]`` was the whole pre-flight, and it is not the question.
WSLg sets DISPLAY when the distro starts and never takes it back, so the
variable says a GUI was BUILT, not that a client can reach it today.  The
renderer then degrades to headless on purpose (a broken X server must not end
a run that is otherwise fine) and the user is left with the emulator's least
diagnosable state: everything works except the picture.

MEASURED, on real WSLg, before any of this was written (see padpath.sh's own
comment for the transcript): a private mount namespace with a fresh tmpfs over
/tmp - which is what systemd's tmp.mount does to WSLg's bind - hides
``/tmp/.X11-unix/X0`` while ``/mnt/wslg/.X11-unix/X0`` stays.  The real
padglhost in that namespace prints "XOpenDisplay failed (DISPLAY=:0); staying
headless"; after ``mount --bind /mnt/wslg/.X11-unix /tmp/.X11-unix`` the same
binary prints "window opened 1920x1080 on DISPLAY=:0".

These tests drive the REAL shell functions - padpath.sh is sourced exactly as
watch.sh sources it - with both socket directories pointed at tmp_path, so
none of it needs a WSL, an X server, a mount or root.  What they cannot reach
is the mount itself, so ``mount`` and ``id`` are stand-ins and what is checked
is the argv the repair builds and that it VERIFIES the result rather than
trusting an exit code.
"""
import os
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def src(name):
    with open(os.path.join(RIG, name), encoding="utf8", errors="replace") as f:
        return f.read()


def line_of(text, needle):
    """1-based line number of the first line containing `needle`."""
    for i, line in enumerate(text.split("\n"), 1):
        if needle in line:
            return i
    raise AssertionError("not found: %r" % needle)


#: EVERYTHING RELATIVE, AND THE SCRIPT ON DISK: the same rule test_spike2_emu_
#: build.py records - on Windows `bash` is as likely to be WSL's launcher as
#: Git's, and that one sees a C:\... path as a name with no directories in it.
#: AND DISPLAY SET INSIDE THE SCRIPT, for the same reason one line further on:
#: a WSL `bash` starts a distro whose environment is its own, and nothing from
#: this process crosses that boundary unless WSLENV names it - while WSLg has
#: already set DISPLAY=:0 in there.  Passing it in `env` therefore worked under
#: Git's bash and was silently ignored under WSL's, where every case became the
#: `:0` one: three of these tests asked about a display they had not set and the
#: `unix:` / `:0.0` spellings were never exercised at all.  Every other input
#: here already arrives as a line of the script; this is now one too.
_DRIVER = """#!/bin/bash
%s
RIG=$(pwd); export RIG
PATH=$RIG/bin:$PATH; export PATH
PAD_HOME=$RIG; export PAD_HOME
PAD_X11_DIR=$RIG/x11; export PAD_X11_DIR
PAD_WSLG_X11_DIR=$RIG/wslg; export PAD_WSLG_X11_DIR
. "$RIG/padpath.sh"
echo "STATE=$(pad_display_state)"
echo "SOCKET=$(pad_x_socket)"
echo "FIX=$(pad_display_fix_cmd)"
echo "WINLINE=$(pad_window_line "$RIG/hostlog")"
if pad_display_repair; then echo "REPAIR=ok"; else echo "REPAIR=refused"; fi
echo "AFTER=$(pad_display_state)"
[ -f "$RIG/mount.argv" ] && echo "MOUNT=$(cat "$RIG/mount.argv")" || echo "MOUNT="
exit 0
"""


def _drive(tmp_path, display, local=(), wslg=(), root=False, mount_works=False,
           hostlog=None):
    """Ask the real functions what this synthetic machine's display is.

    `local` / `wslg` are the socket names present in each directory - `-e`, not
    `-S`, is what the functions test, precisely so a machine that cannot create
    a UNIX socket (Windows) can still exercise every state.
    """
    # A rig per CALL: several tests ask about two machines, and a second
    # synthetic display must not inherit the first one's sockets.
    rig = tmp_path / ("rig%d" % len(list(tmp_path.glob("rig*"))))
    (rig / "bin").mkdir(parents=True)
    (rig / "x11").mkdir()
    (rig / "wslg").mkdir()
    shutil.copy(os.path.join(RIG, "padpath.sh"), str(rig / "padpath.sh"))
    for name in local:
        (rig / "x11" / name).write_text("socket", encoding="utf-8")
    for name in wslg:
        (rig / "wslg" / name).write_text("socket", encoding="utf-8")
    if hostlog is not None:
        with open(str(rig / "hostlog"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(hostlog)
    # The stand-ins.  `mount` always records what it was asked to do; whether it
    # then DOES anything is the difference between the two repair tests.
    body = '#!/bin/sh\necho "$*" > "$RIG/mount.argv"\n'
    if mount_works:
        body += 'cp "$RIG/wslg/"* "$RIG/x11/" 2>/dev/null\n'
    body += "exit 0\n"
    scripts = [("bin/mount", body)]
    if root:
        # padpath.sh asks `id -u` at source time as well, and PAD_HOME above is
        # already set, so answering 0 to everything is safe here.
        scripts.append(("bin/id", "#!/bin/sh\necho 0\n"))
    if display is None:
        setdisplay = "unset DISPLAY"
    else:
        setdisplay = "DISPLAY='%s'; export DISPLAY" % display
    scripts.append(("driver.sh", _DRIVER % setdisplay))
    for name, text in scripts:
        path = rig / name
        with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(str(path), 0o755)
    env = dict(os.environ)
    env["RIG"] = str(rig)
    out = subprocess.run([BASH, "driver.sh"], cwd=str(rig), env=env,
                         capture_output=True, text=True)
    facts = {}
    for line in (out.stdout + out.stderr).splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            facts[key.strip()] = value.strip()
    return facts


# ---- what the display IS --------------------------------------------------

@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_no_display_at_all(tmp_path):
    """The state the old guard was the whole of, and it keeps its answer."""
    assert _drive(tmp_path, None)["STATE"] == "none"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_local_display_with_its_socket_is_ok(tmp_path):
    """The ordinary machine.  Nothing above it may cost this one anything."""
    facts = _drive(tmp_path, ":0", local=("X0",))
    assert facts["STATE"] == "ok"
    assert facts["SOCKET"].endswith("/x11/X0")


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_screen_number_is_read_rather_than_assumed(tmp_path):
    """`:2` is X2.  A hard-coded X0 would clear a machine whose display is not
    the first one, and condemn one whose is."""
    facts = _drive(tmp_path, ":2", local=("X2",))
    assert facts["STATE"] == "ok"
    assert facts["SOCKET"].endswith("/x11/X2")
    assert _drive(tmp_path, ":2", local=("X0",))["STATE"] == "nosocket"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_screen_suffix_and_the_unix_form_are_the_same_display(tmp_path):
    """`:0.0` and `unix:0` are both the local socket - X's own spellings."""
    for spelling in (":0.0", "unix:0", "unix:0.0"):
        assert _drive(tmp_path, spelling, local=("X0",))["STATE"] == "ok", spelling


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_hostname_is_not_ours_to_judge(tmp_path):
    """VcXsrv, X410, a Linux box across the room: TCP, no socket here, and no
    verdict either.  Guessing would take the emulator away from a machine whose
    display works perfectly."""
    facts = _drive(tmp_path, "192.168.1.9:0")
    assert facts["STATE"] == "remote"
    assert facts["SOCKET"] == ""
    assert _drive(tmp_path, "localhost:0.0")["STATE"] == "remote"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_hidden_wslg_socket_is_its_own_state(tmp_path):
    """The systemd-over-/tmp machine: WSLg's socket is right there, one
    directory away, and only the copy libX11 opens is missing.  It is a
    different answer from "there is no X server" because it has a cure."""
    assert _drive(tmp_path, ":0", wslg=("X0",))["STATE"] == "masked"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_nothing_anywhere_is_nosocket(tmp_path):
    """DISPLAY names a socket that does not exist and cannot be got back."""
    assert _drive(tmp_path, ":0")["STATE"] == "nosocket"


# ---- and what putting it back looks like ----------------------------------

@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_repair_binds_wslgs_own_directory(tmp_path):
    """Root, a masked socket, and a mount that works: the state becomes ok and
    the command is the one the message tells a non-root user to run."""
    facts = _drive(tmp_path, ":0", wslg=("X0",), root=True, mount_works=True)
    assert facts["STATE"] == "masked"
    assert facts["REPAIR"] == "ok"
    assert facts["AFTER"] == "ok"
    assert facts["MOUNT"].startswith("--bind ")
    assert facts["MOUNT"].endswith("/x11")
    assert "/wslg" in facts["MOUNT"]
    assert facts["FIX"] == "mount --bind %s" % facts["MOUNT"][len("--bind "):]


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_mount_that_said_ok_and_did_nothing_is_not_a_repair(tmp_path):
    """The verdict comes from asking again, not from an exit code.  A repair
    that reported success over a still-missing socket would turn one honest
    message into a run that fails later for no stated reason."""
    facts = _drive(tmp_path, ":0", wslg=("X0",), root=True, mount_works=False)
    assert facts["REPAIR"] == "refused"
    assert facts["AFTER"] == "masked"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_nothing_is_mounted_over_a_display_that_works(tmp_path):
    """A machine with a display gets no mounts, no repairs and no advice."""
    facts = _drive(tmp_path, ":0", local=("X0",), root=True, mount_works=True)
    assert facts["REPAIR"] == "refused"
    assert facts["MOUNT"] == "", "a working display must not be touched"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_repair_refuses_when_there_is_nothing_to_put_back(tmp_path):
    """nosocket is not repairable, and trying anyway would mount an empty
    directory over the place the socket should be."""
    facts = _drive(tmp_path, ":0", root=True, mount_works=True)
    assert facts["REPAIR"] == "refused"
    assert facts["MOUNT"] == ""


# ---- what the renderer did with its window ---------------------------------

#: The three lines padglhost really prints, copied from padglhost.c.
_OPENED = "[padglhost] window opened 1445x827 on DISPLAY=:0\n"
_NO_X = ("[padglhost] PAD_GL_WINDOW=1 but XOpenDisplay failed (DISPLAY=:0); "
         "staying headless\n")
_NO_SURFACE = ("[padglhost] eglCreateWindowSurface failed 0x3009; "
               "falling back to headless\n")


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_an_opened_window_is_read_as_opened(tmp_path):
    facts = _drive(tmp_path, ":0", local=("X0",),
                   hostlog="[padglhost] ring 64 MB\n" + _OPENED)
    assert "window opened 1445x827" in facts["WINLINE"]


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_headless_renderer_is_read_as_headless(tmp_path):
    facts = _drive(tmp_path, ":0", local=("X0",), hostlog=_NO_X)
    assert "staying headless" in facts["WINLINE"]


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_headless_beats_an_opened_line_above_it(tmp_path):
    """THE ORDER IS THE TRAP.  The window is mapped before the EGL surface is
    asked for, so a surface failure prints BOTH lines with "opened" first - and
    that run has a window on the desktop that can never show a picture.  Taking
    the first match would report it as healthy."""
    facts = _drive(tmp_path, ":0", local=("X0",),
                   hostlog=_OPENED + _NO_SURFACE)
    assert "falling back to headless" in facts["WINLINE"]


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_log_that_says_neither_says_nothing(tmp_path):
    """The renderer has not got there yet.  Inventing an answer here would be
    the same fault as the one being fixed, pointed the other way."""
    facts = _drive(tmp_path, ":0", local=("X0",),
                   hostlog="[padglhost] ring 64 MB\n")
    assert facts["WINLINE"] == ""
    assert _drive(tmp_path, ":0", local=("X0",))["WINLINE"] == ""


# ---- where the run asks, and what it does with the answer ------------------

def test_the_display_is_checked_before_the_renderer_is_started():
    """A pre-flight after the renderer is a post-mortem.  Everything from the
    renderer on takes ~15 s to reach the first picture."""
    text = src("watch.sh")
    check = line_of(text, "case $(pad_display_state) in")
    renderer = line_of(text, "starting renderer")
    assert check < renderer


def test_a_hidden_socket_is_repaired_rather_than_reported():
    """The app's own launch is root, which is exactly what this mount needs -
    so the common case costs the user nothing at all."""
    text = src("watch.sh")
    body = text[text.index("case $(pad_display_state) in"):]
    body = body[:body.index("\nesac")]
    assert "pad_display_repair" in body
    # ...and the branch that cannot repair prints the command instead of a
    # description of it.
    assert "sudo $(pad_display_fix_cmd)" in body


def test_a_linux_desktop_is_warned_and_a_wsl_is_stopped():
    """On WSL a local DISPLAY is that socket and nothing else, so the verdict
    is conclusive.  On a Linux desktop it is only probable - and refusing a
    machine that works is the worse mistake."""
    text = src("watch.sh")
    body = text[text.index("case $(pad_display_state) in"):]
    body = body[:body.index("\nesac")]
    tail = body[body.index("no X server at"):]
    guard = tail.index('if [ "$IS_WSL" = 1 ]')
    assert guard < tail.index("exit 1"), "only WSL stops here"
    assert "Continuing anyway" in tail


def test_the_run_says_whether_the_game_window_opened():
    """The renderer has always answered this into its own log.  The point of
    the verdict is that it is said HERE, where the app's log pane and a
    terminal run both show it."""
    text = src("watch.sh")
    started = line_of(text, "starting renderer")
    verdict = line_of(text, 'GLWIN=$(pad_window_line "$HOSTLOG")')
    game = line_of(text, 'starting $GAME (boot to the first picture')
    assert started < verdict < game
    assert "THE RENDERER HAS NO WINDOW" in text


def test_no_window_is_reported_and_not_fatal():
    """A headless run still boots the guest, plays sound and answers the
    playfield.  Taking that away over a window would be the worse trade - and
    the ffmpeg fault (PAD-49) settled the same question the same way."""
    text = src("watch.sh")
    body = text[text.index('GLWIN=$(pad_window_line "$HOSTLOG")'):]
    body = body[:body.index("\nesac")]
    assert "exit" not in body, "the verdict reports; it does not stop the run"


def test_a_window_that_opened_names_the_one_thing_left_to_blame():
    """Nothing inside Linux can see the Windows desktop, so a window that IS
    open is as far as the rig can go - and it is far enough to point at WSLg's
    mirror rather than at the emulator."""
    text = src("watch.sh")
    body = text[text.index('GLWIN=$(pad_window_line "$HOSTLOG")'):]
    body = body[:body.index("\nesac")]
    assert "Restart WSL" in body


def test_the_renderers_own_headless_lines_reach_the_event_feed():
    """Both of them end in the word `headless` and neither begins with one of
    the four the feed already forwarded, which is how the state stayed
    invisible while the log was open on screen."""
    text = src("watch.sh")
    assert r"/\[padglhost\] .*headless/" in text
    host = src("padglhost.c")
    assert "staying headless" in host
    assert "falling back to headless" in host


# ---- and what an unset DISPLAY is told to do about it ----------------------
#
# Reported 2026-08-12 (Pinside, #151-#153).  The `none` branch used to be four
# lines, and the only thing it named was `guiApplications=false in
# %USERPROFILE%\.wslconfig`.  The tester who met it HAD NO SUCH FILE, read the
# line as an instruction to make one, and said so: "I followed instructions
# online to create the .wslconfig text file but unsure if I just dump those
# strings in there or what."  The only string he had been given was the one
# that SWITCHES GUI APPS OFF - so the message was one paste away from causing
# the fault it describes, on a machine whose real cure (a restart) it
# mentioned only as the last clause of the last line.


def _none_branch():
    """The advice an unset DISPLAY prints, and nothing around it.

    COMMENTS STRIPPED, because these tests are about what the USER reads.
    This branch's comment block quotes the old wording it replaced - the
    `guiApplications=false` line included - so a test that searched the raw
    text would be answered by the history rather than by the message.
    """
    text = src("watch.sh")
    body = text[text.index("case $(pad_display_state) in"):]
    body = body[:body.index("\nesac")]
    start = body.index("    none)")
    body = body[start:body.index("exit 1 ;;", start)]
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_restart_leads_and_the_settings_file_follows():
    """The cure that actually worked for the machine that reported this, said
    first.  The settings file is the rarer cause and reads as a red herring
    where it is not the fault."""
    body = _none_branch()
    assert body.index("Restart WSL") < body.index(".wslconfig")


def test_the_missing_file_is_named_as_the_healthy_state():
    """No .wslconfig means GUI apps are ON.  Without that sentence the advice
    sends someone who has no such file off to write one."""
    body = _none_branch()
    assert "OPTIONAL" in body
    assert "do not create it" in body


def test_nothing_here_can_be_read_as_add_this_line():
    """`guiApplications=false` may only ever appear as something to LOOK FOR
    and undo.  It must never be the last thing a confused reader copies."""
    body = _none_branch()
    said = [ln for ln in body.splitlines() if "guiApplications" in ln]
    assert said, "the setting is no longer named at all"
    for line in said:
        assert "already exists" in line or "Only if" in line, line
    # ...and the sentence that follows says what to do with it.
    assert "change that word to true" in body
    assert "delete the line" in body


def test_a_wsl_too_old_for_wslg_is_named_too():
    """No restart cures that one, and nothing inside the distro can see it -
    so a message that offers only the restart sends that machine round a loop
    it cannot leave."""
    body = _none_branch()
    assert "wsl --update" in body


def test_a_linux_desktop_is_not_sent_to_a_windows_settings_file():
    """%USERPROFILE% means nothing on a Linux box with no DISPLAY, and the
    branch is reached there too - the same wrong-machine advice the `nosocket`
    branch below has always been careful to avoid."""
    body = _none_branch()
    assert '[ "$IS_WSL" = 1 ]' in body
    wsl_half, _, linux_half = body.partition("else")
    assert ".wslconfig" in wsl_half
    assert ".wslconfig" not in linux_half
    assert "DISPLAY" in linux_half
