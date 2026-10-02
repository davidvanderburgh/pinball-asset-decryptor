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
        self.names = dict(CAB)            # cabinet names -> bits (+ the game's launch)
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
        target, key = (self.cabinet, self.names[switch]) if isinstance(switch, str) \
            else (self.matrix, int(switch))
        if closed:
            target.add(key)
        else:
            target.discard(key)
        self._rows(self.pic.lat["D"])


class Balls:
    """The balls, for a game in ``games.GAMES``: a trough that fills from its
    eject end, the shooter lane, and the balls in play.

    The game's LOAD coil moves a ball from the trough into the shooter lane
    (its switch closes 300 ms later); its PLUNGER coil launches it (the lane
    opens and the ball is in play). ``drain()`` sends a ball in play back
    to the trough. Everything else on the playfield is the player's: press
    its switches.
    """
    ROLL_MS = 300

    def __init__(self, board, game, count=None):
        from tools.pinheck_emu.games import coil_pins
        self.board = board
        self.trough = list(game["trough"])
        self.shooter_sw = game["shooter"]
        self.in_trough = len(self.trough) if count is None else count
        self.in_shooter = False
        self.in_play = 0
        self._due = []                  # (millis, fn)
        pins = coil_pins()
        self._load = pins[game["load"]]
        self._plunge = pins[game["plunge"]]
        self.ready_bit = game.get("ready")
        if game.get("launch") is not None:
            board.names["launch"] = game["launch"]
        board.pic.on_lat.append(self._lat)
        board.pic.on_ms.append(self._tick)
        self._now = 0
        self._show()

    def _show(self):
        for i, sw in enumerate(self.trough):
            self.board.set(sw, i < self.in_trough)
        self.board.set(self.shooter_sw, self.in_shooter)
        if self.ready_bit is not None:
            if self.in_trough:
                self.board.cabinet.add(self.ready_bit)
            else:
                self.board.cabinet.discard(self.ready_bit)

    def _later(self, ms, fn):
        self._due.append((self._now + ms, fn))

    def _tick(self, millis):
        self._now = millis
        due = [e for e in self._due if e[0] <= millis]
        if due:
            self._due = [e for e in self._due if e[0] > millis]
            for _, fn in due:
                fn()
            self._show()

    def _lat(self, port, old, new):
        rose = lambda pin: port == pin[0] and new & pin[1] and not old & pin[1]
        if rose(self._load) and self.in_trough and not self.in_shooter:
            self.in_trough -= 1
            self._show()

            def arrive():
                self.in_shooter = True
            self._later(self.ROLL_MS, arrive)
        elif rose(self._plunge) and self.in_shooter:
            self.in_shooter = False
            self.in_play += 1
            self._show()

    def drain(self):
        """A ball in play falls to the trough."""
        if not self.in_play:
            return False
        self.in_play -= 1

        def land():
            self.in_trough = min(self.in_trough + 1, len(self.trough))
        self._later(self.ROLL_MS, land)
        return True
