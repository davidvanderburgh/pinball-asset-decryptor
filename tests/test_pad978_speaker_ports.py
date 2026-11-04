"""PAD-978: a Spike 1 speaker left up silenced the next slot-1 Spike 2 game.

Iron Maiden in Visual Pinball played with no sound. Its relay could not listen
("Address already in use") because the Game of Thrones run before it - the
Spike 1 rig - had left its own relay up on 45998, which is also Spike 2 slot
1's port (45997 + slot). Three faults, each pinned here:

* Spike 1's port sat inside the Spike 2 slot range;
* stop.sh matched its speaker on /home/*/s1emu, where the FIFO no longer is
  (S1_WORK moved to /mnt/wsl/paddata/spike1), so the speaker outlived every run;
* the relay's bind failure was a traceback in padaudio.log only.

(Proven live in PAD-Runtime: a relay holding a port, a second one failing on
it, playaudio.sh reaping the leftover and a player attaching to the new one,
and the new stop.sh stopping a speaker the old pattern did not match.)
"""
import os
import re
import socket
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S1 = os.path.join(ROOT, "tools", "spike1_emu")
S2 = os.path.join(ROOT, "tools", "spike2_emu")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def _code(text):
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_spike1_port_is_outside_every_spike2_slot():
    m = re.search(r'S1_AUDIO_PORT:=(\d+)', _read(S1, "prereqs.sh"))
    assert m
    port = int(m.group(1))
    slots = int(re.search(r'PAD_SLOTS_MAX:=(\d+)',
                          _read(S2, "padpath.sh")).group(1))
    assert not 45997 <= port <= 45997 + slots
    from pinball_decryptor.webui import emulate_spike1_core as s1
    assert s1.AUDIO_PORT == port       # the app's player dials the rig's port


def test_no_spike1_script_still_names_45998():
    for name in ("start.sh", "stop.sh", "prereqs.sh"):
        assert "45998" not in _code(_read(S1, name)), name
    tab = _read(ROOT, "pinball_decryptor", "webui", "tabs", "emulate_spike1.py")
    assert '"45998"' not in tab
    start = _code(_read(S1, "start.sh"))
    assert 'PAD_AUDIO_PORT="$S1_AUDIO_PORT"' in start


def test_stop_matches_the_speaker_where_start_puts_it():
    stop = _code(_read(S1, "stop.sh"))
    assert '. "$HERE/prereqs.sh"' in stop and "s1_paths" in stop
    assert stop.index("s1_paths") < stop.index("playaudio.sh")
    assert '"$S1_WORK/audio.fifo"' in stop
    assert "* $S1_AUDIO_PORT *" in stop
    start = _code(_read(S1, "start.sh"))
    assert 'S1_AUDIO_FIFO="$S1_WORK/audio.fifo"' in start


def test_playaudio_reaps_a_leftover_relay_on_its_port_before_listening():
    pa = _code(_read(S2, "playaudio.sh"))
    assert 'pat="padrelay\\.py [^ ]+ $1( |\\$)"' in pa
    for sink in ('if [ "$SINK" = relay ]', 'if [ "$SINK" = win ]'):
        body = pa[pa.index(sink):]
        assert body.index('reap_port_relay "$PORT"') < body.index("padrelay.py")


def test_relay_says_in_a_play_line_when_its_port_is_taken():
    holder = socket.socket()
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):     # Windows lets REUSEADDR steal
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    holder.bind(("0.0.0.0", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        r = subprocess.run([sys.executable, os.path.join(S2, "padrelay.py"),
                            os.path.join(ROOT, "no.fifo"), str(port)],
                           capture_output=True, text=True, timeout=30)
    finally:
        holder.close()
    assert r.returncode == 3
    assert ("[play] NO SOUND this run: the speaker's port %d is taken" % port
            in r.stdout)
    assert "Traceback" not in r.stderr
