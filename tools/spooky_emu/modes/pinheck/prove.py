"""Run a pinHeck PRG (a modes build or stock) in tools/pinheck_emu and show what the modes do
(PAD-1422).  Headless, muted (the sound is never mixed), no window.

    python tools/spooky_emu/modes/pinheck/prove.py <update.zip | PRG --card <card dir>> [--seconds 90]
        [--at 27:sw20] [--at 30:drain] [--at 40:tilt] [--frames DIR] [--frame-at 31,33]

Before the script: coin at 14 s, Start at 15 s, the launch button held 1.2 s at 24 s (Jetsons'
skill shot).  ``--at`` adds events in seconds: ``swN`` closes playfield switch N for 100 ms,
``drain`` drains a ball, ``launch`` holds the launch button 1.2 s, ``tilt`` taps the tilt bob,
``start`` taps Start.  Prints the runtime's own log (its ``[pad]`` lines on the game's serial
monitor), the sound / text / score packets the game sent, and the player's score at the end.
``--frames`` saves the DMD (x4) at the ``--frame-at`` seconds.  ``--json`` writes it all.
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

LAUNCH_HOLD_MS = 1200


def run(prg, card, seconds, at, frames=None, frame_at=(), nvram=None, name="JET_V004.PRG"):
    from tools.pinheck_emu import run as R
    import importlib.util
    spec = importlib.util.spec_from_file_location("pad_pinheck_hooks", os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks.py"))
    H = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(H)
    t = H.HOOKS.get(H.stem_of(name)) or H.HOOKS["JET_V004"]
    from tools.pinheck_emu.games import game_of
    game = game_of(name)
    box, out = [], dict(log=[], packets=[], frames=[], events=[])
    # Jetsons: the launch button (its skill shot); Domino's and Rob Zombie: the hand plunger
    serve = (24.0, "launch") if (game or {}).get("launch") is not None else (20.0, "plunge")
    events = sorted([(14.0, "coin"), (15.0, "start"), serve] + list(at))
    state = {"uart": 0, "releases": []}

    def on_ms(ms):
        if not box:
            return
        link = box[0]
        pic = link.board.pic
        for t, what in events:
            if int(t * 1000) != ms:
                continue
            out["events"].append((t, what))
            if what.startswith("sw"):
                link.board.set(int(what[2:]), True)
                state["releases"].append((ms + 100, int(what[2:])))
            elif what == "drain":
                out["events"][-1] = (t, "drain (%s)" % ("a ball drained" if link.balls.drain() else "no ball in play"))
            elif what == "plunge":
                out["events"][-1] = (t, "plunge (%s)" % ("the ball goes" if link.balls.plunge() else "no ball in the lane"))
            elif what == "launch":
                link.board.set("launch", True)
                state["releases"].append((ms + LAUNCH_HOLD_MS, "launch"))
            elif what in ("tilt", "start", "coin"):
                link.board.set(what, True)
                state["releases"].append((ms + 150, what))
        for r in [r for r in state["releases"] if r[0] == ms]:
            link.board.set(r[1], False)
            state["releases"].remove(r)
        if len(pic.uart) > state["uart"]:
            text = bytes(pic.uart[state["uart"]:]).decode("latin1")
            if "\n" in text:
                done, _, _ = text.rpartition("\n")
                for line in done.split("\n"):
                    line = line.strip("\r")
                    if line.startswith("[pad]"):
                        out["log"].append((round(ms / 1000, 3), line[6:]))
                state["uart"] += len(done) + 1
        if frames and any(int(f * 1000) == ms for f in frame_at) and link.av:
            img = link.av.frame(ms)
            p = os.path.join(frames, "%07d.png" % ms)
            img.resize((img.width * 4, img.height * 4)).save(p)
            out["frames"].append(p)

    def log(pkt):
        if not box or pkt[15] not in (0x01, 0x03, 0x06, 0x0F, 0x12, 0x13):
            return
        ms = box[0].board.pic.millis
        if pkt[15] == 0x01:
            what = "sound " + "".join(chr(b) for b in pkt[0:5] if 48 <= b < 91)
        elif pkt[15] == 0x03:
            what = "score[%d] = %d" % (pkt[0], int.from_bytes(pkt[1:5], "little"))
        elif pkt[15] == 0x0F:
            if t.get("text_abi") != "amh" or pkt[0] > 1:
                return                      # the game's own ticker (line 6) and the rest
            what = "text line %d %r" % (pkt[0], bytes(pkt[1:15]).split(b"\0")[0].decode("latin1"))
        elif pkt[15] == 0x12:
            what = "text col %d line %d %r" % (pkt[0] >> 3, pkt[0] & 7, bytes(pkt[1:15]).split(b"\0")[0].decode("latin1"))
        elif pkt[15] == 0x13:
            what = "text layer %s" % ("on" if pkt[1] else "off") if pkt[0] == 3 else "13 " + pkt.hex()
        else:
            if not (pkt[0] < 8 and all(b == 0xFF for b in pkt[1:8])):
                return
            what = "text line %d cleared" % pkt[0]
        out["packets"].append((round(ms / 1000, 3), what))

    if frames:
        os.makedirs(frames, exist_ok=True)
    pic, link = R.boot(prg, seconds, log, card, nvram, (), (), on_ms=[on_ms], link_box=box, game=game)
    player = pic.mu.mem_read(t["player"] & 0x1FFFFFFF, 1)[0]
    out["player"] = player
    out["score"] = struct.unpack("<I", pic.mu.mem_read((t["score_array"] + 4 * (player or 1)) & 0x1FFFFFFF, 4))[0]
    out["ran_ms"] = pic.millis
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("prg")
    ap.add_argument("--card", help="the card folder (DMD/, SFX/); an update zip brings its own")
    ap.add_argument("--cache", help="where an update zip is unpacked (default: the pinHeck window's cache)")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--at", action="append", default=[])
    ap.add_argument("--frames")
    ap.add_argument("--frame-at", default="")
    ap.add_argument("--nvram")
    ap.add_argument("--json")
    ap.add_argument("--name", help="the PRG's stock name (JET_V004.PRG) when the file is named otherwise")
    a = ap.parse_args(argv)
    at = []
    for s in a.at:
        t, _, what = s.partition(":")
        at.append((float(t), what.strip().lower()))
    name = a.name or os.path.basename(a.prg)
    if a.prg.lower().endswith(".zip"):          # an update: its PRG on its own card, as the window runs it
        from tools.pinheck_emu.machine import unpack
        prg_path, card = unpack(a.prg, a.cache)
        a.prg, name = prg_path, os.path.basename(prg_path)
        a.card = a.card or card
    if not a.card:
        ap.error("--card is needed for a PRG")
    prg = open(a.prg, "rb").read()
    fa = [float(x) for x in a.frame_at.split(",") if x.strip()]
    r = run(prg, a.card, a.seconds, at, a.frames, fa, a.nvram, name)
    merged = sorted([(t, "     ", "%s" % w) for t, w in r["events"]] +
                    [(t, "[pad]", w) for t, w in r["log"]] +
                    [(t, " pkt ", w) for t, w in r["packets"]], key=lambda e: e[0])
    for t, k, w in merged:
        print("%8.3f %s %s" % (t, k, w))
    print("ran %.1f s; player %d score %d" % (r["ran_ms"] / 1000, r["player"], r["score"]))
    if r["frames"]:
        print("frames:", " ".join(r["frames"]))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(r, f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
