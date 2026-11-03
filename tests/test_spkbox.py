"""PAD-953: the Spooky emulator on a Mac runs in a container, through
tools/spooky_emu/docker/spkbox.sh.

The box is started idle and every rig script - watch.sh included - is a
`docker exec` into it, because watch.sh returns at attract and leaves the game
running. These run the real spkbox.sh against a `docker` stand-in that prints
what it was asked (and a `uname` that says Darwin where the Mac's copying is
the point), as test_padbox_mac_sharing.py does for the Spike 2 box.
"""
import os
import subprocess

import pytest

from tests.conftest import HAS_BASH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spooky_emu")
BOX = os.path.join(RIG, "docker", "spkbox.sh")

needs_bash = pytest.mark.skipif(not (os.path.isfile(BOX) and HAS_BASH),
                                reason="rig or working bash not present")

# $W/home is HOME; $W/apps/app is an installed app outside it (/Applications),
# $W/home/dev/app a checkout under it. Each holds the files the box mounts.
_FAKE = r"""
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/bin" "$W/home/games" "$W/ctl"
for a in "$W/apps/app" "$W/home/dev/app"; do
    mkdir -p "$a/tools/spooky_emu/docker" "$a/tools/proc_emu" "$a/tools/ap_emu" \
             "$a/tools/spike2_emu/pfpage" "$a/pinball_decryptor/plugins/spooky"
    echo x > "$a/tools/spooky_emu/watch.sh"
    echo x > "$a/tools/spike2_emu/pfweb.py"
    echo x > "$a/tools/rigboard.sh"
    echo keys > "$a/pinball_decryptor/plugins/spooky/games.py"
    echo FROM > "$a/tools/spooky_emu/docker/Dockerfile"
    echo x > "$a/tools/spooky_emu/docker/entrypoint.sh"
done
echo pkg > "$W/home/games/ac-gamecode.pkg"
cat > "$W/bin/docker" <<'EOF'
#!/bin/bash
echo "DOCKER $*" >> "$W/log"
# also out: `exec docker ...` replaces the script, so no EXIT trap reads the log
case "$*" in exec*) echo "DOCKER $*" ;; esac
case "$1" in
    ps) [ -f "$W/up" ] && echo pad-spooky; exit 0 ;;
    rm) rm -f "$W/up"; exit 0 ;;
    run) case " $* " in *" -d "*) touch "$W/up" ;; esac; exit 0 ;;
    exec)
        case "$*" in
            *"cat /run/pad-box.ready"*) echo 48000 ;;
            *"test -f"*) [ -f "$W/hidden" ] && exit 1 ;;
            *watch.sh*) echo "== Ready =="; exit "${FAKE_RC:-0}" ;;
            *status.sh*) echo "wsl=1"; echo "running=1" ;;
        esac
        exit 0 ;;
esac
exit 0
EOF
printf '#!/bin/bash\necho Darwin\n' > "$W/bin/uname"
chmod +x "$W/bin/"*
export W PATH="$W/bin:$PATH" HOME="$W/home"
"""


def _box(where, args, env="", setup=""):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    # $0 is the shell under `bash -s`, so SELF is pinned to the fake app's rig
    pin = 'SELF=$(cd "$(dirname "$0")" && pwd)'
    assert pin in body
    body = body.replace(pin, 'SELF=$(cd "$W/%s/app/tools/spooky_emu/docker" && pwd)'
                        % where, 1)
    prelude = "\n".join([_FAKE, setup, "set -- %s" % args,
                         "export PAD_SPK_BOX_IMAGE=pad953-test:1 %s" % env, ""])
    # spkbox.sh exits; the log is read from an EXIT trap that runs first
    prelude += 'trap \'echo "--LOG--"; cat "$W/log" 2>/dev/null; ' \
               'ls -R "$W/home/Library" 2>/dev/null; rm -rf "$W"\' EXIT\n'
    out = subprocess.run(["bash", "-s"],
                         input=(prelude + body).encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, text


def _lines(text, prefix):
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


@needs_bash
def test_a_start_runs_an_idle_amd64_box_then_watch_sh_inside_it():
    rc, text = _box("home/dev", 'watch.sh "$W/home/games/ac-gamecode.pkg"',
                    env='PAD_SLOT=0 PAD_VISIBLE=1 PAD_AUDIO=0 '
                        'PAD_TITLE=Alice PAD_AUDIO_CTL="$W/ctl/audio_ctl.json"')
    assert rc == 0, text
    run = [ln for ln in _lines(text, "DOCKER run ") if " -d " in ln]
    assert len(run) == 1, text
    run = run[0]
    # Intel games: the image runs as amd64 everywhere (Rosetta / qemu on
    # Apple silicon); privileged for run_game.sh's namespaces
    assert "--platform linux/amd64" in run and "--privileged" in run
    # under home: the checkout itself is mounted, read only, at /pad/app
    assert "/home/dev/app:/pad/app:ro" in run
    assert "/home/games:/pad/files:ro" in run
    assert "/ctl:/pad/ctl:ro" in run
    assert "127.0.0.1:5901:5900" in run and "127.0.0.1:45998:45998" in run
    text = text.split("--LOG--", 1)[1]
    watch = [ln for ln in _lines(text, "DOCKER exec ") if "watch.sh" in ln]
    assert len(watch) == 1, text
    w = watch[0]
    assert "-u 0" in w
    assert "/pad/app/tools/spooky_emu/watch.sh /pad/files/ac-gamecode.pkg" in w
    assert "-e PAD_SLOT=0" in w and "-e PAD_VISIBLE=1" in w
    assert "-e PAD_TITLE=Alice" in w
    # the host's Volume / Mute file, as the box sees it
    assert "-e PAD_AUDIO_CTL=/pad/ctl/audio_ctl.json" in w
    # a run that reached attract keeps its box
    assert not [ln for ln in _lines(text, "DOCKER rm ")
                if text.index(ln) > text.index(w)]


@needs_bash
def test_a_failed_start_removes_the_box():
    rc, text = _box("home/dev", 'watch.sh "$W/home/games/ac-gamecode.pkg"',
                    env="FAKE_RC=6")
    assert rc == 6, text
    log = text.split("--LOG--", 1)[1]
    assert log.rstrip().splitlines()[-1].startswith("DOCKER rm -f pad-spooky")


@needs_bash
def test_a_file_the_engine_cannot_see_is_said_not_run():
    """A folder the engine does not share is EMPTY in the box (PAD-884)."""
    rc, text = _box("home/dev", 'watch.sh "$W/home/games/ac-gamecode.pkg"',
                    setup='touch "$W/hidden"')
    assert rc == 4, text
    assert "cannot see" in text and "home folder" in text
    assert not [ln for ln in _lines(text, "DOCKER exec ") if "watch.sh" in ln]


@needs_bash
def test_an_installed_app_is_copied_under_home_with_the_games_keys():
    """/Applications is not shared by colima: the rig, the rigs it borrows
    from and the Spooky plugin's games.py (the .pkg keys) go under home."""
    rc, text = _box("apps", 'watch.sh "$W/home/games/ac-gamecode.pkg"')
    assert rc == 0, text
    run = [ln for ln in _lines(text, "DOCKER run ") if " -d " in ln][0]
    stage = "/home/Library/Application Support/pinball_decryptor/spooky_box"
    assert stage + ":/pad/app:ro" in run
    assert "/apps/app:/pad/app" not in run
    listing = text.split("--LOG--", 1)[1]
    for f in ("games.py", "watch.sh", "pfweb.py", "rigboard.sh"):
        assert f in listing, listing


@needs_bash
def test_status_with_no_box_is_the_rigs_idle_answer():
    rc, text = _box("home/dev", "status.sh")
    assert rc == 0
    out = [ln for ln in text.split("--LOG--")[0].splitlines()
           if not ln.startswith("DOCKER ")]
    assert out == ["wsl=1", "running=0"]


@needs_bash
def test_status_with_a_box_asks_the_box_as_root():
    rc, text = _box("home/dev", "status.sh", setup='touch "$W/up"')
    assert rc == 0, text
    ex = [ln for ln in _lines(text, "DOCKER exec ") if "status.sh" in ln]
    assert ex and "-u 0" in ex[0] and "pad-spooky bash /pad/app/tools/spooky_emu/status.sh" in ex[0]


@needs_bash
def test_stop_runs_the_rigs_stop_then_removes_the_box():
    rc, text = _box("home/dev", "stop.sh", setup='touch "$W/up"')
    assert rc == 0, text
    log = text.split("--LOG--", 1)[1].splitlines()
    i = next(n for n, ln in enumerate(log) if "stop.sh" in ln)
    assert log[i].startswith("DOCKER exec -u 0 pad-spooky bash")
    assert any(ln.startswith("DOCKER rm -f pad-spooky") for ln in log[i:])


@needs_bash
def test_the_playfield_opens_in_the_box_as_pad_on_its_screen():
    rc, text = _box("home/dev", "playfield /var/tmp/pad_spkproc/rig0/switches.json",
                    env='PAD_AUDIO_CTL="$W/ctl/audio_ctl.json"',
                    setup='touch "$W/up"')
    assert rc == 0, text
    ex = [ln for ln in _lines(text, "DOCKER exec ") if "spkpf.py" in ln][0]
    assert "-d -u pad -e DISPLAY=:99" in ex
    assert "--table /var/tmp/pad_spkproc/rig0/switches.json" in ex
    assert "--audio-ctl /pad/ctl/audio_ctl.json" in ex


def test_the_rig_plays_to_the_boxs_sound_server_when_told():
    """Both halves of the rig take their PulseAudio socket from
    PAD_PULSE_SOCK (the box's, entrypoint.sh) and default to WSLg's."""
    for f, var in (("spkpath.sh", "SPK_PULSE"), ("proc/sppath.sh", "SPP_PULSE")):
        with open(os.path.join(RIG, f), encoding="utf-8") as fh:
            assert "%s=${PAD_PULSE_SOCK:-/mnt/wslg/PulseServer}" % var in fh.read()
    for f in ("run_game.sh", "proc/run_game.sh"):
        with open(os.path.join(RIG, f), encoding="utf-8") as fh:
            code = [ln for ln in fh.read().splitlines()
                    if not ln.lstrip().startswith("#")]
        assert not [ln for ln in code if "/mnt/wslg/PulseServer" in ln], f
    with open(os.path.join(RIG, "docker", "Dockerfile"), encoding="utf-8") as fh:
        assert "PAD_PULSE_SOCK=/run/pad-pulse/native" in fh.read()


def test_the_mac_build_carries_the_spooky_rig():
    with open(os.path.join(ROOT, "installer", "build_macos.sh"),
              encoding="utf-8") as fh:
        build = fh.read()
    for src in ("tools/spooky_emu:tools/spooky_emu",
                "tools/proc_emu:tools/proc_emu", "tools/ap_emu:tools/ap_emu",
                "tools/rigboard.sh:tools",
                "pinball_decryptor/plugins/spooky/games.py:"
                "pinball_decryptor/plugins/spooky"):
        assert '--add-data "$ROOT_DIR/%s"' % src in build, src
