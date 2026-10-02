"""The pinHeck game CPU: a PIC32MX795F512L running a <GAME>_Vnnn.PRG (PAD-320).

The PRG is raw program flash from 0x9D000000 (chipKIT Max32 core, app
``_reset`` at 0x9D001000), run unmodified on Unicorn (MIPS32 LE). Only the
parts of the chip the games touch are modelled:

* GPIO ports A..G (TRIS/PORT/LAT with the CLR/SET/INV shadows). Outputs go
  to ``on_lat`` listeners; inputs come from ``pins_in`` (what the board drives
  onto the pins, idle high), read back through PORTx.
* UART1..6 transmit: everything the game prints lands in ``uart`` (UART1 is
  its serial monitor). UART1 receive: ``serial_in()`` types into it (the
  game's ``[E99000]``-style commands), interrupt driven like chipKIT's
  HardwareSerial.
* Timers 1..5 and the interrupt controller. Unicorn has no PIC32 EIC, so
  interrupts are delivered by hand between slices of instructions: when a
  flag in IFSx is set, enabled in IECx and Status.IE is on, the CPU is sent
  to the vector stub (EBASE 0x9D000000 + 0x200 + 0x20 * vector; chipKIT's
  stubs jump through a RAM table) and run until the handler's ``eret``,
  which is caught and turned into a return to where the main code was. One
  instruction is counted as one 80 MHz clock (PBCLK = SYSCLK on a Max32).
  Lamp (Timer2) and switch (Timer3) handlers run at their real rates.
* I2C1 master, interrupt driven as chipKIT's Wire library uses it, with
  devices plugged in by 7-bit address (``i2c_devices``). An address nobody
  answers is NAKed, as on a real bus.
* CP0 Count (the core timer, SYSCLK/2): Unicorn's never moves, and
  ``micros()``/``delayMicroseconds()`` spin on it (the switch handler waits
  1 us per column). Every ``mfc0 rt,$9`` in the PRG (three in Jetsons and
  Domino's) is patched to a nop and a hook fills rt with clock/2, moved on
  by 8 per read inside a slice so a spin loop always gets out.
* Idle skip: the games' main loop spends ~3/4 of the CPU spinning on
  ``while (millis() == last);`` (about 74% of instructions in Jetsons'
  attract; 2% go to interrupt handlers), and boot is full of ``delay()``.
  Both loops are found by their code (``find_idle_loops``); a hook on the
  loop's branch ends the slice when it is about to go round again, and the
  main code stays parked until the next millisecond. Timer and I2C
  interrupts still run at their own clocks, so only instructions that could
  not change anything are skipped. ``idle_skip = False`` runs every one.
* ``millis()``: the core-timer interrupt is NOT delivered (Unicorn's CP0
  Count/Compare do not follow our clock); instead the core's millisecond
  counter is bumped once per 80 000 instructions. Its address is found from
  ``delay()``'s code.

Physical map (kseg0/kseg1 strip the top 3 bits):
  0x1D000000 program flash   0x1FC00000 boot flash (the ISR trampoline)
  0x00000000 RAM 128 KB      0x1F800000 SFRs
"""
import collections
import struct

from unicorn import (Uc, UcError, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN,
                     UC_HOOK_CODE)
from unicorn.mips_const import (UC_MIPS_REG_0, UC_MIPS_REG_CP0_STATUS, UC_MIPS_REG_GP, UC_MIPS_REG_K0,
                                UC_MIPS_REG_K1, UC_MIPS_REG_PC)

FLASH = 0x9D000000
FLASH_SIZE = 0x80000
RESET = 0x9D001000
SFR = 0x1F800000
PORTS = "ABCDEFG"
PORT_BASE = 0x1F886000          # TRISA; each port is 0x40 long
UART_BASES = (0x1F806000, 0x1F806200, 0x1F806400, 0x1F806600, 0x1F806800, 0x1F806A00)
MS = 80_000                     # instructions per emulated millisecond
ERET = 0x42000018
MFC0_COUNT, MFC0_COUNT_MASK = 0x40004800, 0xFFE0FFFF    # mfc0 rt, $9, 0
# boot flash (unused by the app): mtc0 k0,EPC; ehb; jr k1; nop
TRAMPOLINE = 0x9FC00000
TRAMPOLINE_CODE = (0x409A7000, 0x000000C0, 0x03600008, 0x00000000)

IFS0, IEC0, IPC0 = 0x1F881030, 0x1F881060, 0x1F881090
# timer n: (TxCON, IRQ = vector); PRx is TxCON + 0x20
TIMERS = {1: (0x1F800600, 4), 2: (0x1F800800, 8), 3: (0x1F800A00, 12),
          4: (0x1F800C00, 16), 5: (0x1F800E00, 20)}
T1_PRESCALE = (1, 8, 64, 256)
TX_PRESCALE = (1, 2, 4, 8, 16, 32, 64, 256)
# IRQ -> vector for the sources modelled (PIC32MX795 data sheet, table 7-1)
IRQ_VECTOR = {4: 4, 8: 8, 12: 12, 16: 16, 20: 20, 26: 24, 27: 24, 28: 24,
              29: 25, 30: 25, 31: 25}
I2C1, I2C1_MASTER_IRQ = 0x1F805300, 31
U1RX_IRQ = 27
SEN, RSEN, PEN, RCEN, ACKEN = 1, 2, 4, 8, 16
ACKSTAT, RBF = 1 << 15, 1 << 1


WAIT, DELAY = "wait", "delay"


def _gp_off(word):
    off = word & 0xFFFF
    return off - 0x10000 if off & 0x8000 else off


def find_idle_loops(prg, gpoff):
    """{branch address: kind} for the loops that only wait for millis():

    WAIT  ``while (millis() == last);``:  ``jal G; nop; lw v1,last(gp);
          beq v0,v1,-4`` where G is the getter ``lw v0,<millis>(gp); jr ra``
    DELAY chipKIT's ``delay()``:  ``lw v0,<millis>(gp); subu v0,v0,s1;
          sltu v0,v0,s0; bnez v0,back`` (the back edge calls the task
          scheduler, which only runs tasks that are due by millis)."""
    found = {}
    for o in range(0, min(len(prg), FLASH_SIZE) - 16, 4):
        w0, w1, w2, w3 = struct.unpack_from("<4I", prg, o)
        if w0 >> 16 == 0x8F82 and _gp_off(w0) == gpoff and w1 == 0x00511023 \
                and w2 == 0x0050102B and w3 >> 16 == 0x1440:
            found[FLASH + o + 12] = DELAY
        if w0 >> 26 != 3 or w1 or w2 >> 16 != 0x8F83 or w3 != 0x1043FFFC:
            continue
        g = ((FLASH & 0xF0000000) | ((w0 & 0x3FFFFFF) << 2)) - FLASH
        if not 0 <= g < len(prg) - 8:
            continue
        g0, g1 = struct.unpack_from("<2I", prg, g)
        if g0 >> 16 == 0x8F82 and g1 == 0x03E00008 and _gp_off(g0) == gpoff:
            found[FLASH + o + 12] = WAIT
    return found


def find_millis_gp_offset(prg):
    """The gp offset of the core's millis counter, from delay()'s loop:
    ``lw v0,off(gp); subu v0,v0,s1; sltu v0,v0,s0``."""
    for i in range(0x1000, len(prg) - 12, 4):
        w0, w1, w2 = struct.unpack_from("<3I", prg, i)
        if w1 == 0x00511023 and w2 == 0x0050102B and (w0 >> 16) == 0x8F82:
            off = w0 & 0xFFFF
            return off - 0x10000 if off & 0x8000 else off
    raise ValueError("not a pinHeck PRG: no delay() loop found")


class Pic32:
    def __init__(self, prg, chipkit=True):
        """``chipkit=False`` runs bare code (tests): no millis() to bump."""
        self.prg = prg
        self.mu = mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN)
        mu.mem_map(0x1D000000, FLASH_SIZE)
        mu.mem_write(0x1D000000, prg[:FLASH_SIZE])
        mu.mem_map(0x00000000, 0x20000)
        mu.mem_map(0x1FC00000, 0x3000)
        mu.mem_write(0x1FC00000, struct.pack("<4I", *TRAMPOLINE_CODE))
        self.sfr = collections.defaultdict(int)
        self.lat = {p: 0 for p in PORTS}
        # inputs idle high: the board's switch and button lines are pulled up
        self.pins_in = {p: 0xFFFF for p in PORTS}
        self.on_lat = []            # f(port, old, new)
        self.on_ms = []             # f(millis), after every emulated millisecond
        self.uart = bytearray()
        self.uart_rx = collections.deque()  # bytes typed into the serial monitor
        self.i2c_devices = {}       # 7-bit address -> device (see I2CDevice)
        self.i2c_log = collections.deque(maxlen=1000)  # (address, 'w'|'r', bytes), latest
        self._i2c = None            # [address, read?, data, address next?] of the open transfer
        self.irq_counts = collections.Counter()
        self._deferred = []         # IRQs raised by peripherals, flagged after the slice
        self.clock = 0              # instructions run = 80 MHz clocks
        self._next = {}             # timer n -> clock of its next period match
        mu.mmio_map(SFR, 0x100000, self._read, None, self._write, None)
        self._gpoff = find_millis_gp_offset(prg) if chipkit else None
        self.pc = RESET
        self.millis_addr = None
        self._in_isr = False
        self._count = 0
        self.idle_skip = True
        self.idle_stops = 0
        self._parked = False        # main code idle until millis() moves
        self._resumed_at = None     # the idle branch the main code resumes on
        self._idle_loops = find_idle_loops(prg, self._gpoff) if chipkit else {}
        for a, kind in self._idle_loops.items():
            mu.hook_add(UC_HOOK_CODE, self._idle, begin=a, end=a, user_data=kind)
        for o in range(0, min(len(prg), FLASH_SIZE) - 3, 4):
            w = struct.unpack_from("<I", prg, o)[0]
            a = FLASH + o
            if w == ERET:
                mu.hook_add(UC_HOOK_CODE, self._eret, begin=a, end=a)
            elif w & MFC0_COUNT_MASK == MFC0_COUNT:
                mu.mem_write(0x1D000000 + o, bytes(4))         # nop
                mu.hook_add(UC_HOOK_CODE, self._read_count, begin=a, end=a,
                            user_data=UC_MIPS_REG_0 + ((w >> 16) & 31))

    # --- SFRs ---------------------------------------------------------------
    def _port(self, a):
        if PORT_BASE <= a < PORT_BASE + 0x40 * len(PORTS):
            return PORTS[(a - PORT_BASE) // 0x40], (a - PORT_BASE) % 0x40
        return None, None

    def _read(self, uc, off, size, data):
        a = SFR + off
        port, reg = self._port(a)
        if port is not None:
            tris = self.sfr[PORT_BASE + PORTS.index(port) * 0x40]
            if reg & ~3 == 0x10:                                # PORTx
                return (self.lat[port] & ~tris) | (self.pins_in[port] & tris)
            if reg & ~3 == 0x20:                                # LATx
                return self.lat[port]
        if (a & ~0x1FF) in UART_BASES and (a & 0x1FF) == 0x10:  # UxSTA
            rx = 1 if a == UART_BASES[0] + 0x10 and self.uart_rx else 0     # URXDA
            return 0x100 | (self.sfr[a] & ~1) | rx              # TRMT, never full
        if a == UART_BASES[0] + 0x30:                           # U1RXREG
            if not self.uart_rx:
                return 0
            b = self.uart_rx.popleft()
            if self.uart_rx:
                self._deferred.append(U1RX_IRQ)
            return b
        if a == 0x1F80F000:                                     # OSCCON: PLL locked
            return self.sfr[a] | 0x20
        return self.sfr[a & ~3]

    def _write(self, uc, off, size, value, data):
        a = SFR + off
        r, shadow = a & ~0xF, a & 0xF
        port, reg = self._port(r)
        if port is not None and reg in (0x10, 0x20):           # PORTx/LATx write the latch
            old = self.lat[port]
            new = (value if shadow == 0 else old & ~value if shadow == 4
                   else old | value if shadow == 8 else old ^ value) & 0xFFFF
            self.lat[port] = new
            if new != old:
                for f in self.on_lat:
                    f(port, old, new)
            return
        if shadow == 4:
            self.sfr[r] &= ~value
        elif shadow == 8:
            self.sfr[r] |= value
        elif shadow == 0xC:
            self.sfr[r] ^= value
        else:
            self.sfr[a] = value
        if (a & ~0x1FF) in UART_BASES and (a & 0x1FF) == 0x20:  # UxTXREG
            self.uart.append(value & 0xFF)
        elif r == I2C1 or r == I2C1 + 0x50:
            self._i2c_step(r == I2C1 + 0x50, value & 0xFF)
        elif any(r == con for con, _ in TIMERS.values()):
            self._next.clear()                                  # re-time the timers

    def serial_in(self, data):
        """Type ``data`` into the game's serial monitor (UART1 RX)."""
        self.uart_rx.extend(data)
        self._deferred.append(U1RX_IRQ)

    # --- I2C1 master ----------------------------------------------------------
    def _i2c_step(self, trn, byte):
        con, stat = I2C1, I2C1 + 0x10
        c = self.sfr[con]
        done = True
        if trn:                                     # I2C1TRN: send a byte
            if self._i2c is None or self._i2c[3]:   # first byte after (re)start
                self._close_i2c()
                self._i2c = [byte >> 1, byte & 1, bytearray(), False]
                dev = self.i2c_devices.get(byte >> 1)
                ack = dev is not None and dev.start(byte & 1)
            else:
                dev = self.i2c_devices.get(self._i2c[0])
                self._i2c[2].append(byte)
                ack = dev is not None and dev.write(byte)
            self.sfr[stat] = (self.sfr[stat] & ~ACKSTAT) | (0 if ack else ACKSTAT)
        elif c & (SEN | RSEN):
            if self._i2c is not None:
                self._i2c[3] = True                 # next TRN is an address
            else:
                self._i2c = [None, 0, bytearray(), True]
            self.sfr[con] = c & ~(SEN | RSEN)
        elif c & RCEN:
            dev = self.i2c_devices.get(self._i2c[0]) if self._i2c else None
            b = dev.read() & 0xFF if dev else 0xFF
            if self._i2c:
                self._i2c[2].append(b)
            self.sfr[I2C1 + 0x60] = b
            self.sfr[stat] |= RBF
            self.sfr[con] = c & ~RCEN
        elif c & ACKEN:
            self.sfr[con] = c & ~ACKEN
        elif c & PEN:
            self._close_i2c()
            self._i2c = None
            self.sfr[con] = c & ~PEN
        else:
            done = False
        if done:                                    # a bus event takes time:
            self._deferred.append(I2C1_MASTER_IRQ)  # flag it after this slice

    def _close_i2c(self):
        t = self._i2c
        if t and t[0] is not None:
            self.i2c_log.append((t[0], "r" if t[1] else "w", bytes(t[2])))
            dev = self.i2c_devices.get(t[0])
            if dev is not None:
                dev.stop()

    # --- interrupts -----------------------------------------------------------
    def raise_irq(self, irq):
        self.sfr[IFS0 + 0x10 * (irq // 32)] |= 1 << (irq % 32)

    def _priority(self, vec):
        return (self.sfr[IPC0 + 0x10 * (vec // 4)] >> (8 * (vec % 4) + 2)) & 7

    def _pending(self):
        best = None
        for irq, vec in IRQ_VECTOR.items():
            reg, bit = 0x10 * (irq // 32), 1 << (irq % 32)
            if self.sfr[IFS0 + reg] & bit and self.sfr[IEC0 + reg] & bit:
                p = self._priority(vec)
                if p and (best is None or p > best[0]):
                    best = (p, vec, irq)
        return best

    def _idle(self, uc, address, size, kind):
        if not self.idle_skip or self._in_isr:
            return
        # The stop lands before the branch and the hook fires again when the
        # main code resumes there: let that one pass, so the loop goes round
        # once and reads the new millis() before it is judged again.
        if self._resumed_at == address:
            self._resumed_at = None
            return
        v0 = uc.reg_read(UC_MIPS_REG_0 + 2)
        spinning = (v0 == uc.reg_read(UC_MIPS_REG_0 + 3)) if kind == WAIT else v0 != 0
        if spinning:
            self.idle_stops += 1
            self._parked = True
            self._resumed_at = address
            uc.emu_stop()

    def _read_count(self, uc, address, size, reg):
        self._count = max(self._count + 8, self.clock // 2) & 0xFFFFFFFF
        uc.reg_write(reg, self._count)

    def _eret(self, uc, address, size, data):
        if self._in_isr:
            self._erets += 1
            uc.emu_stop()

    def _service(self):
        """Run every pending, enabled handler to its eret."""
        for _ in range(8):
            if self.mu.reg_read(UC_MIPS_REG_CP0_STATUS) & 7 != 1:   # IE off, or EXL/ERL
                return
            hit = self._pending()
            if hit is None:
                return
            _, vec, irq = hit
            self.irq_counts[vec] += 1
            self._in_isr, self._erets = True, 0
            # the trampoline puts the return address in EPC: the handler
            # saves and restores EPC, and if Unicorn runs the eret before the
            # hook's stop lands, it returns there instead of to 0
            self.mu.reg_write(UC_MIPS_REG_K0, self.pc)
            self.mu.reg_write(UC_MIPS_REG_K1, FLASH + 0x200 + 0x20 * vec)
            try:
                self.mu.emu_start(TRAMPOLINE, 0x7FFFFFFC, count=MS)
            except UcError as e:                    # spurious on a stop, as in _slice
                pc = self.mu.reg_read(UC_MIPS_REG_PC)
                if not FLASH <= pc < FLASH + FLASH_SIZE:
                    raise RuntimeError("vector %d handler stopped at %08x: %s" % (vec, pc, e))
            finally:
                self._in_isr = False
            if not self._erets:
                raise RuntimeError("vector %d handler ran %d instructions without returning (pc %08x)"
                                   % (vec, MS, self.mu.reg_read(UC_MIPS_REG_PC)))

    def _timer_period(self, n):
        con, _ = TIMERS[n]
        c = self.sfr[con]
        if not c & 0x8000:
            return None
        pre = T1_PRESCALE[(c >> 4) & 3] if n == 1 else TX_PRESCALE[(c >> 4) & 7]
        return (self.sfr[con + 0x20] + 1) * pre

    # --- running --------------------------------------------------------------
    def _slice(self, count):
        try:
            self.mu.emu_start(self.pc, 0x7FFFFFFC, count=count)
        except UcError as e:
            pc = self.mu.reg_read(UC_MIPS_REG_PC)
            # Unicorn reports a spurious READ_UNMAPPED when a counted slice
            # ends; only a stop outside flash is real.
            if not FLASH <= pc < FLASH + FLASH_SIZE:
                raise RuntimeError("game CPU stopped at %08x: %s" % (pc, e))
        self.pc = self.mu.reg_read(UC_MIPS_REG_PC)
        self.clock += count     # an idle stop counts the rest of the slice as passed

    @property
    def insns(self):
        return self.clock

    @property
    def millis(self):
        if self._gpoff is None:
            return self.clock // MS
        return struct.unpack("<I", self.mu.mem_read(self.millis_addr, 4))[0]

    def run_ms(self, ms):
        """Run ``ms`` emulated milliseconds."""
        if self.millis_addr is None and self._gpoff is not None:   # crt0 sets gp first
            self._slice(2000)
            self.millis_addr = (self.mu.reg_read(UC_MIPS_REG_GP) + self._gpoff) & 0x1FFFFFFF
        for _ in range(ms):
            end = self.clock + MS
            while self.clock < end:
                for n in TIMERS:
                    if n not in self._next:
                        per = self._timer_period(n)
                        if per:
                            self._next[n] = self.clock + per
                step = min([end] + list(self._next.values())) - self.clock
                if self._parked:
                    self.clock += max(step, 100)    # nothing to run but handlers
                else:
                    self._slice(max(step, 100))
                for irq in self._deferred:
                    self.raise_irq(irq)
                self._deferred.clear()
                for n, due in list(self._next.items()):
                    if self.clock >= due:
                        self.raise_irq(TIMERS[n][1])
                        self._next[n] = due + (self._timer_period(n) or MS)
                self._service()
            if self._gpoff is not None:
                self.mu.mem_write(self.millis_addr, struct.pack("<I", (self.millis + 1) & 0xFFFFFFFF))
            self._parked = False
            for f in self.on_ms:
                f(self.millis)


class I2CDevice:
    """A device on the I2C bus. ``start`` returns True to ACK its address."""
    def start(self, read):
        return True

    def write(self, byte):
        return True

    def read(self):
        return 0xFF

    def stop(self):
        pass
