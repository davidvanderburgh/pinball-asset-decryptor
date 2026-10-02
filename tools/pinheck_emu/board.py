"""The pinHeck board's switch inputs, seen from the game CPU's pins (PAD-320).

Cabinet ("dedicated") switches: a 16-bit parallel-in shift register. Every
houseKeeping() pass (twice a millisecond in Jetsons) the PIC pulses the coil
enable (RG15), then 16 times: puts a GI bit on RG7, pulses the clock RE0 and
reads RF0, building ``cabinet`` MSB first from the inverted reads; then the
latch RG8 low-high loads the next snapshot. So the read after the k-th clock
(k = 1..16) is bit 16-k of ``cabinet``, low = closed. Bit numbers are AMH's
(github.com/benheck/AMH gs_pins.h): Door 1, RFlip 3, LFlip 4, Menu 5, Enter 6,
Coin 7, Tilt 8, Start 12. The Door switch is closed when the coin door is
shut, so it starts closed here.

Playfield matrix: 8 x 8, scanned in the Timer3 handler. LATD's high byte
drives one row low (RD8 = row 0), PORTD's low byte reads the columns, low =
closed; switch n = row * 8 + column (AMH's ``switches[]`` layout).
"""
CAB = {"door": 1, "rflip": 3, "lflip": 4, "menu": 5, "enter": 6, "coin": 7,
       "tilt": 8, "start": 12}
CLOCK, LATCH, DATA = ("E", 1 << 0), ("G", 1 << 8), ("F", 1 << 0)


class Board:
    def __init__(self, pic):
        self.pic = pic
        self.cabinet = {CAB["door"]}      # closed cabinet switches (bit numbers)
        self.matrix = set()               # closed playfield switches (0..63)
        self._snapshot = 0
        self._k = 0
        pic.on_lat.append(self._lat)
        self._latch()
        self._rows(pic.lat["D"])

    # --- cabinet shift register ---------------------------------------------
    def _latch(self):
        self._snapshot = sum(1 << b for b in self.cabinet)
        self._k = 0
        self._data()

    def _data(self):
        bit = 16 - self._k
        closed = 0 <= bit < 16 and (self._snapshot >> bit) & 1
        port, mask = DATA
        if closed:
            self.pic.pins_in[port] &= ~mask
        else:
            self.pic.pins_in[port] |= mask

    def _lat(self, port, old, new):
        if port == CLOCK[0] and new & CLOCK[1] and not old & CLOCK[1]:
            self._k += 1
            self._data()
        elif port == LATCH[0] and not new & LATCH[1] and old & LATCH[1]:
            self._latch()
        elif port == "D":
            self._rows(new)

    # --- playfield matrix -----------------------------------------------------
    def _rows(self, latd):
        cols = 0
        for row in range(8):
            if not latd >> (8 + row) & 1:
                for col in range(8):
                    if row * 8 + col in self.matrix:
                        cols |= 1 << col
        self.pic.pins_in["D"] = (self.pic.pins_in["D"] & ~0xFF) | (~cols & 0xFF)

    # --- pressing things ------------------------------------------------------
    def set(self, switch, closed=True):
        """``switch``: a cabinet name (``start``, ``coin`` ...) or a matrix
        number 0..63."""
        target, key = (self.cabinet, CAB[switch]) if isinstance(switch, str) \
            else (self.matrix, int(switch))
        if closed:
            target.add(key)
        else:
            target.discard(key)
        self._rows(self.pic.lat["D"])
