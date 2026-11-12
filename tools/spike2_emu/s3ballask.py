#!/usr/bin/env python3
"""s3ballask.py - the playfield window's ball moves, handed to a Spike 3 bridge.

plunge.py runs this first for its ball verbs: on a Spike 3 slot it answers,
on a Spike 2 rig spike3_dir() is None and plunge.py goes on as it always
did. Its own module because it waits on the bridge in WALL time (a reply
file), and plunge.py keeps every wait in the game's time (padsw.game_sleep).
"""
import os
import time

#: ★ PAD-1181: ON A SPIKE 3 SLOT THE BALL MOVES ARE THE BRIDGE'S. A Spike 3
#: run has no guest shim merging this block's script array: its switches are
#: the node bus's, and its ball model (tools/spike3_emu/s3balls.py) lives in
#: the bridge's loop, which also answers the game's eject and auto plunger.
#: Writing trough switches from here would race that model, so these verbs
#: are handed to it - a request file in the slot's dump/, answered beside
#: it - and the window's Plunge / Drain / Reset balls / trough dots mean on
#: Spike 3 exactly what they mean on Spike 2. Coin and Start stay in plunge.py: a
#: button press is a plain switch, and s3keys.py carries it onto the bus.
S3_VERBS = ("plunge", "drain", "take", "serve", "reset")
S3_REQ, S3_ANS = "s3ballreq.", "s3ballans."
#: How the bridge's refusals start (s3balls.Balls.do_*): exit 1 for those.
S3_REFUSED = ("nothing", "the trough is", "the ball is still", "not ", "a ball is already")
#: The bridge ticks every 50 ms; a move queued behind a drain's roll waits
#: for it (a few hundred ms), so this is generous.
S3_WAIT_S = 5.0


def spike3_dir():
    """The Spike 3 slot's request directory, or None on a Spike 2 rig. A
    Spike 3 slot's root (PAD_ROOT: /var/tmp/pad-s3/slotN) holds the ball
    model's balls.json; a window run's requests go in its dump/."""
    try:
        import padpath
        r = padpath.root()
    except Exception:                                        # noqa: BLE001
        return None
    if not r or not os.path.isfile(os.path.join(r, "balls.json")):
        return None
    d = os.path.join(r, "dump")
    return d if os.path.isdir(d) else r


def spike3_ask(d, what, wait_s=S3_WAIT_S):
    """Hand one ball move to the Spike 3 bridge and print its answer."""
    tag = "%d.%d" % (os.getpid(), int(time.time() * 1000))
    req, ans = os.path.join(d, S3_REQ + tag), os.path.join(d, S3_ANS + tag)
    with open(req + ".tmp", "w") as f:
        f.write(what + "\n")
    os.replace(req + ".tmp", req)
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        if os.path.exists(ans):
            with open(ans) as f:
                text = f.read().strip()
            try:
                os.remove(ans)
            except OSError:
                pass
            # the outcome first, any advice on its own line (do_plunge's shape)
            first, _, rest = text.partition("   ")
            print(first)
            if rest:
                print("  " + rest)
            return 1 if first.startswith(S3_REFUSED) else 0
        time.sleep(0.05)
    try:
        os.remove(req)
    except OSError:
        pass
    print("the Spike 3 ball model did not answer - is the game still running?")
    return 1
