"""Run a pinHeck game's PRG headless and print what it says (PAD-320).

Usage: python -m tools.pinheck_emu.run <GAME_Vnnn.PRG> [seconds]
                [--card DIR] [--sheet PNG] [--nvram DIR] [--quiet]
                [--closed 34,35,32] [--tap coin@15 --tap start@16]

Prints the game's serial monitor (UART1) and every packet it sends the
Propeller (hex + the bytes as text). Jetsons V004 and Domino's V006 get past
"PROPELLER SYNC CHECK" into attract against tools.pinheck_emu.proplink.
``--card`` is the game's SD-card folder (holding DMD/ and SFX/, default:
the PRG's folder); ``--sheet`` saves one frame of every video the game
played, in order - the attract sequence at a glance. ``--nvram`` keeps
both EEPROMs (the board's I2C one and the Propeller's) between runs, as
the machine does between power-ups: on a blank EEPROM a game treats itself
as just updated (Domino's then shows "System has been updated, Please
restart your machine" and waits), so a second run is the normal boot.
``--closed`` holds playfield switches shut (matrix numbers, row * 8 +
column; Jetsons: 34 and 35 are trough balls, 32 the shooter lane - without
the trough a coin shows "MISSING BALLS"); ``--tap name@seconds`` presses a
cabinet switch (start, coin, menu, enter, lflip, rflip, tilt) for 150 ms.
"""
import argparse
import os
import time

from tools.pinheck_emu.av import Av
from tools.pinheck_emu.board import Board
from tools.pinheck_emu.i2c import Eeprom24, Rtc1307
from tools.pinheck_emu.pic32 import Pic32
from tools.pinheck_emu.proplink import PropLink


NVRAM = (("i2c_eeprom.bin", 0x8000), ("prop_eeprom.bin", 8192 * 4))


def _load(nvram, name, size):
    path = os.path.join(nvram, name) if nvram else None
    if path and os.path.isfile(path):
        data = bytearray(open(path, "rb").read())
        if len(data) == size:
            return data
    return None


TAP_MS = 150


def boot(prg, seconds, log=None, card=None, nvram=None, closed=(), taps=(),
         on_ms=(), link_box=None):
    """``taps``: (seconds, cabinet switch name) presses, in any order;
    ``on_ms``: f(millis) after every emulated millisecond; ``link_box``: a
    list the link is appended to before the run starts."""
    pic = Pic32(prg)
    pic.i2c_devices[0x50] = eeprom = Eeprom24(_load(nvram, *NVRAM[0]))
    pic.i2c_devices[0x68] = Rtc1307()
    av = Av(card) if card else None

    def on_packet(pkt):
        if av:
            av.packet(pkt, pic.millis)
        if log:
            log(pkt)

    link = PropLink(pic, on_packet=on_packet, eeprom=_load(nvram, *NVRAM[1]))
    link.av = av
    link.board = board = Board(pic)
    pic.on_ms.extend(on_ms)
    if link_box is not None:
        link_box.append(link)
    for n in closed:
        board.set(int(n))
    # press/release events in emulated ms, run between them
    end = int(seconds * 1000)
    events = sorted(e for e in [(int(t * 1000), n, True) for t, n in taps] +
                    [(int(t * 1000) + TAP_MS, n, False) for t, n in taps] if e[0] < end)
    try:
        now = 0
        for ms, name, down in events + [(end, None, None)]:
            if ms > now:
                pic.run_ms(ms - now)
                now = ms
            if name:
                board.set(name, down)
    finally:
        if nvram:
            os.makedirs(nvram, exist_ok=True)
            for (name, _), data in zip(NVRAM, (eeprom.data, link.eeprom)):
                with open(os.path.join(nvram, name), "wb") as f:
                    f.write(data)
    return pic, link


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("prg")
    ap.add_argument("seconds", nargs="?", type=float, default=8)
    ap.add_argument("--card")
    ap.add_argument("--sheet")
    ap.add_argument("--nvram")
    ap.add_argument("--closed", default="", help="matrix switches held shut, e.g. 34,35")
    ap.add_argument("--tap", action="append", default=[], help="name@seconds, e.g. coin@15")
    ap.add_argument("--frames", help="save the DMD every --every seconds into this folder")
    ap.add_argument("--every", type=float, default=0.5)
    ap.add_argument("--quiet", action="store_true", help="no packet lines")
    a = ap.parse_args(argv)
    prg = open(a.prg, "rb").read()
    card = a.card or os.path.dirname(os.path.abspath(a.prg))

    def log(pkt):
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in pkt)
        print("PKT %s  %s" % (pkt.hex(" "), text))

    t0 = time.time()
    taps = []
    for t in a.tap:
        name, _, at = t.partition("@")
        taps.append((float(at), name.lower()))
    closed = [int(n) for n in a.closed.split(",") if n.strip()]
    frames = []
    if a.frames:
        os.makedirs(a.frames, exist_ok=True)
        step = max(1, int(a.every * 1000))

        def grab(ms):
            if ms % step == 0 and link_box and link_box[0].av:
                img = link_box[0].av.frame(ms)
                if img.getbbox():
                    path = os.path.join(a.frames, "%07d.png" % ms)
                    img.resize((img.width * 4, img.height * 4)).save(path)
                    frames.append(path)
        frame_hooks = [grab]
    else:
        frame_hooks = []
    link_box = []
    pic, link = boot(prg, a.seconds, None if a.quiet else log, card, a.nvram, closed, taps,
                     on_ms=frame_hooks, link_box=link_box)
    print("ran %.1f s emulated (%d M insns) in %.1f s; %d packets"
          % (pic.millis / 1000, pic.insns // 1_000_000, time.time() - t0, len(link.packets)))
    print("interrupts by vector:", dict(pic.irq_counts))
    print("I2C transfers: %d, first: %s" % (len(pic.i2c_log), list(pic.i2c_log)[:6]))
    print("videos:", " ".join("%s@%.1f" % (n or "?", ms / 1000) for ms, n, _ in link.av.played))
    if frames:
        print("frames: %d in %s" % (len(frames), a.frames))
    if a.sheet:
        print("sheet:", a.sheet if link.av.contact_sheet(a.sheet) else "no videos found on the card")
    print("UART:")
    print(pic.uart.decode("latin1"))


if __name__ == "__main__":
    main()
