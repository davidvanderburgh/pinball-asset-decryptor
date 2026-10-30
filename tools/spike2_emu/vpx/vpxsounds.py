#!/usr/bin/env python3
"""vpxsounds.py - a patched table plays the ball, not its own soundtrack (PAD-858).

    python vpxsounds.py "<table.vpx>"        list each sound: kept or muted

The machine's own sound comes from the rig: the real game's music, call-outs
and effects. A tribute table carries a soundtrack of its own as well - Bond's
and Deadpool's songs and voices are sounds inside the .vpx, Aerosmith plays
songs from Visual Pinball's Music folder - and its rules keep running as the
shadow game, so the two played over each other. A patched table keeps the
PLAYFIELD's sounds (ball rolling, flippers, rubbers, bumpers, coils, ramps)
and loses the rest:

  * every embedded sound that is not mechanical becomes 10 ms of silence
    under its own name, so every PlaySound of it still finds it (and a loop
    loops nothing). Mechanical = played on the table's own speakers (output
    "Table"; the backglass output is where tables put music and voices),
    no music / voice / effect prefix (vo_, sfx_, mu_ ...), and a playfield
    word in its name (flipper, rubber, ballroll, Drain_3, kicker_enter ...).
    Anything else - a song, a call-out, Godzilla's "explosion", Black
    Knight's ROM-ripped "Sound-0x0111" - is muted;
  * the script's own `PlayMusic` calls (the Music folder) go to empty subs,
    unless the script defines a PlayMusic of its own (Batman 66 and Iron
    Maiden route theirs to PinUP Player, which PadNoPuP already silences).

Sound streams are not part of the table's signature (vpxfile.py: "nor do
images, sounds or fonts"), so they are rewritten without re-signing.

THE SOUND RECORD (GameStg/Sound<n>, pintable.cpp LoadSoundFromStream):
[i32 len][name] [i32 len][path] [i32 len][lowercase name, older files only]
then for a .wav path (or one without an extension) an 18-byte WAVEFORMATEX,
then [i32 len][data: the file's bytes, or the PCM samples of a wav], then
17 bytes: output target (u8, 0 table / 1 backglass), volume, balance, fade
and the volume again (i32 each). Which layout a record has is decided by its
lengths adding up; one that fits neither is left as it is.
"""
import os
import re
import struct
import sys

TRAILER = 17
OUT_BACKGLASS = 1

# a music / voice / effect sound, whatever else its name says
CUSTOM_RE = re.compile(r"^(vo|sfx|mu|music|song|say|quote|callout|speech|voice|attract|"
                       r"fanfare|b66|mk|stern-svc|scorbit)(?![a-z])", re.I)
# ... or with one of these anywhere in it, though a playfield word is there too
# (Jurassic Park's call-out "shootgoldenball", Rush's "redbarchettahorns",
# "kickdrum", "bumperDino1", "fx_targetbounty", "enterinitials-sound")
CUSTOM_WORDS = ("shoot", "golden", "startball", "crash", "dino", "bomb", "bounty",
                "initials", "endofball", "barchetta", "drum")
# the playfield's own sounds
MECH = ("ball", "roll", "flip", "rubber", "metal", "wood", "plastic", "wire", "ramp",
        "drain", "trough", "plunge", "kick", "saucer", "scoop", "hole", "popper", "vuk",
        "eject", "sling", "bumper", "target", "drop", "dtreset", "gate", "spinner",
        "sensor", "trigger", "switch", "solenoid", "solon", "soloff", "coil", "relay",
        "motor", "diverter", "post", "magnet", "knock", "nudge", "coin", "button",
        "apron", "arch", "wall", "collide", "bounce", "pinhit", "peg", "release",
        "launch", "shake", "gion", "gioff", "flasher", "lockup", "subway", "enter",
        "playfield", "rollover", "bridge", "rotary")

SILENT_RATE = 44100
SILENT_SAMPLES = 441      # 10 ms
WAVEFORMAT = struct.pack("<HHIIHHH", 1, 1, SILENT_RATE, SILENT_RATE * 2, 2, 16, 0)


def _is_wav(path):
    """PinSound::IsWav2: a .wav, or a path with no extension."""
    ext = os.path.splitext(path)[1]
    return ext == "" or ext.lower() == ".wav"


def read_sound(data):
    """The record's fields, or None when its lengths fit no known layout."""
    for strings in (3, 2):
        try:
            o, parts = 0, []
            for _ in range(strings):
                n = struct.unpack_from("<i", data, o)[0]
                if n < 0 or o + 4 + n > len(data):
                    raise ValueError
                parts.append(data[o + 4:o + 4 + n])
                o += 4 + n
            path = parts[1].decode("latin-1")
            wav = _is_wav(path)
            fmt = data[o:o + 18] if wav else b""
            o += len(fmt)
            n = struct.unpack_from("<i", data, o)[0]
            if n < 0 or o + 4 + n + TRAILER != len(data):
                continue
            return {"name": parts[0].decode("latin-1"), "path": path,
                    "lower": parts[2] if strings == 3 else None, "wav": wav,
                    "size": n, "trailer": data[o + 4 + n:]}
        except (struct.error, ValueError):
            continue
    return None


def mechanical(name, output):
    """Whether a sound is the playfield's own (kept) rather than the table's
    music, voice or effects (muted). See the module doc."""
    if output == OUT_BACKGLASS or CUSTOM_RE.match(name):
        return False
    low = name.lower()
    return not any(w in low for w in CUSTOM_WORDS) and any(w in low for w in MECH)


def silent(snd):
    """The same record as 10 ms of 16-bit mono silence."""
    def s(b):
        return struct.pack("<i", len(b)) + b
    path = (snd["path"] or snd["name"]) + ".pad-muted.wav"
    out = s(snd["name"].encode("latin-1")) + s(path.encode("latin-1"))
    if snd["lower"] is not None:
        out += s(snd["lower"])
    pcm = bytes(SILENT_SAMPLES * 2)
    return out + WAVEFORMAT + s(pcm) + snd["trailer"]


def survey(ole):
    """[(stream, record or None, kept)] for every sound of an open table."""
    out, i = [], 0
    while ole.exists("GameStg/Sound%d" % i):
        stream = "Sound%d" % i
        snd = read_sound(ole.openstream("GameStg/" + stream).read())
        out.append((stream, snd, snd is None or mechanical(snd["name"], snd["trailer"][0])))
        i += 1
    return out


def quiet_streams(ole, rep):
    """{stream name under GameStg: new bytes} muting the table's own music,
    voices and effects; a line for the patch report."""
    streams, muted, kept, odd = {}, [], 0, []
    for stream, snd, keep in survey(ole):
        if snd is None:
            odd.append(stream)
        elif keep:
            kept += 1
        else:
            streams[stream] = silent(snd)
            muted.append(snd["name"])
    rep.append("sounds: kept %d of the playfield's, muted %d of the table's own music, "
               "voices and effects" % (kept, len(muted)))
    if odd:
        rep.append("WARNING: sound record(s) of an unknown layout left as they are: %s"
                   % ", ".join(odd))
    return streams


# ---- the script: PlayMusic (Visual Pinball's Music folder)

MUSIC_SUB_RE = re.compile(r"^\s*(Public\s+|Private\s+)?Sub\s+PlayMusic\b", re.I)
MUSIC_CALL_RE = re.compile(r"\bPlayMusic\b", re.I)


def _statement_end(line, start):
    """Where the statement that runs from `start` ends (`:` or a comment)."""
    inq = False
    for i in range(start, len(line)):
        ch = line[i]
        if ch == '"':
            inq = not inq
        elif not inq and ch in ":'":
            return i
    return len(line)


def _argcount(text):
    """How many arguments a call's text passes; `Call PlayMusic(a, b)` (the
    parentheses around the whole list) counts what is inside them."""
    text = re.split(r"\s+Else\b", text, maxsplit=1, flags=re.I)[0].strip()
    if text.startswith("("):
        depth, inq = 0, False
        for i, ch in enumerate(text):
            if ch == '"':
                inq = not inq
            elif not inq and ch == "(":
                depth += 1
            elif not inq and ch == ")":
                depth -= 1
                if depth == 0:
                    if not text[i + 1:].strip():
                        text = text[1:i]
                    break
    depth, inq, n, seen = 0, False, 0, False
    for ch in text:
        if ch == '"':
            inq = not inq
        elif not inq:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                n += 1
        if not ch.isspace():
            seen = True
    return (n + 1) if seen else 0


def _in_string(line, i):
    return line[:i].count('"') % 2 == 1


def quiet_music(lines, rep):
    """Every `PlayMusic ...` call becomes `PadNoMusic<n> ...` (n = its
    argument count); returns the empty subs to append. Nothing when the
    script has a PlayMusic Sub of its own."""
    if any(MUSIC_SUB_RE.match(ln) for ln in lines):
        rep.append("music: the script's own PlayMusic is left to it")
        return ""
    used = set()
    for i, line in enumerate(lines):
        if line.strip().startswith("'"):
            continue
        out, pos = [], 0
        for mo in MUSIC_CALL_RE.finditer(line):
            if mo.start() < pos or _in_string(line, mo.start()):
                continue
            q = line.find("'")
            if q != -1 and not _in_string(line, q) and q < mo.start():
                break
            n = max(1, _argcount(line[mo.end():_statement_end(line, mo.end())]))
            used.add(n)
            out.append(line[pos:mo.start()] + "PadNoMusic%d" % n)
            pos = mo.end()
        if out:
            lines[i] = "".join(out) + line[pos:]
    if not used:
        return ""
    rep.append("music: PlayMusic (the Music folder) goes nowhere")
    subs = ["", "'---- PAD: the machine plays the music; the table's own songs stay quiet"]
    for n in sorted(used):
        subs.append("Sub PadNoMusic%d(%s) : End Sub" % (n, ", ".join("a%d" % k for k in range(n))))
    return "\n".join(subs) + "\n"


def quiet(script, ole, rep):
    """A patcher's one call: (the script with its PlayMusic quieted, the
    sound streams to write_patched with)."""
    lines = script.split("\n")
    subs = quiet_music(lines, rep)
    return "\n".join(lines) + subs, quiet_streams(ole, rep)


def quiet_in_place(path):
    """A table patched before PAD-858 still carries its soundtrack: quiet it
    where it is, once (the tab's Play runs this). Sounds already muted are
    left alone, so a quiet table costs one read. Returns the report lines,
    [] when there was nothing to do."""
    import vpxfile
    table = vpxfile.VpxTable(path)
    rep = []
    streams, muted = {}, 0
    for stream, snd, keep in survey(table.ole):
        if snd is None or keep:
            continue
        if snd["path"].endswith(".pad-muted.wav"):
            muted += 1
            continue
        streams[stream] = silent(snd)
    script = table.script()
    lines = script.split("\n")
    subs = quiet_music(lines, [])
    new = "\n".join(lines) + subs
    table.ole.close()
    if not streams and new == script:
        return []
    tmp = path + ".pad-quiet.tmp"
    vpxfile.write_patched(path, tmp, script=new if new != script else None, streams=streams)
    check = vpxfile.VpxTable(tmp)
    ok = check.verify()
    check.ole.close()
    if not ok:
        os.remove(tmp)
        return ["WARNING: %s quieted does not verify; left as it was" % os.path.basename(path)]
    os.replace(tmp, path)
    rep.append("sounds: muted %d more of the table's own music, voices and effects%s"
               % (len(streams), "; PlayMusic goes nowhere" if new != script else ""))
    return rep


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    import olefile
    ole = olefile.OleFileIO(argv[1])
    for stream, snd, keep in survey(ole):
        if snd is None:
            print("%-10s ?    (unknown layout)" % stream)
        else:
            print("%-10s %-5s %s %s" % (stream, "keep" if keep else "MUTE", snd["name"],
                                        "(backglass)" if snd["trailer"][0] == OUT_BACKGLASS else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
