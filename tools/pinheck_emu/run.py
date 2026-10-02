"""Run a pinHeck game's PRG headless and print what it says (PAD-320).

Usage: python -m tools.pinheck_emu.run <GAME_Vnnn.PRG> [seconds]

Prints the game's serial monitor (UART1) and every packet it sends the
Propeller (hex + the bytes as text). Jetsons V004 and Domino's V006 get past
"PROPELLER SYNC CHECK" to "HANDSHAKE DONE" against tools.pinheck_emu.proplink.
"""
import sys
import time

from tools.pinheck_emu.i2c import Eeprom24, Rtc1307
from tools.pinheck_emu.pic32 import Pic32
from tools.pinheck_emu.proplink import PropLink


def boot(prg, seconds, log=None):
    pic = Pic32(prg)
    pic.i2c_devices[0x50] = Eeprom24()
    pic.i2c_devices[0x68] = Rtc1307()
    link = PropLink(pic, on_packet=log)
    pic.run_ms(int(seconds * 1000))
    return pic, link


def main(argv):
    prg = open(argv[1], "rb").read()
    seconds = float(argv[2]) if len(argv) > 2 else 8

    def log(pkt):
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in pkt)
        print("PKT %s  %s" % (pkt.hex(" "), text))

    t0 = time.time()
    pic, link = boot(prg, seconds, log)
    print("ran %.1f s emulated (%d M insns) in %.1f s; %d packets"
          % (pic.millis / 1000, pic.insns // 1_000_000, time.time() - t0, len(link.packets)))
    print("interrupts by vector:", dict(pic.irq_counts))
    print("I2C transfers: %d, first: %s" % (len(pic.i2c_log), list(pic.i2c_log)[:6]))
    print("UART:")
    print(pic.uart.decode("latin1"))


if __name__ == "__main__":
    main(sys.argv)
