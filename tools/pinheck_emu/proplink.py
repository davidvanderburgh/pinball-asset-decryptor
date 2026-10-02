"""The PIC32 <-> Propeller command link of the pinHeck board (PAD-320).

A bit-banged clocked serial link on chipKIT pins 16 (SDO, RF5), 15 (CLK,
RF12) and 14 (SDI, RF13). Per bit the PIC sets SDO, pulses CLK high then
low, then reads SDI; bytes go LSB first, 16 bytes a packet. The Propeller
clocks its own 16 bytes back during the same packet, so what the PIC reads
was prepared from the packets before it.

This end stands in for the Propeller: it frames the PIC's bits into packets,
hands each one to ``on_packet`` and clocks out ``reply`` (16 bytes).

Packets seen so far:
* Sync (colour games' "PROPELLER SYNC CHECK"): byte 0 = 0xAA, bytes 1..14 =
  '0'..'=', byte 15 = '#'. The Propeller answers with the pattern moved down
  to bytes 0..13 and 0xAA, 0xAA in 14 and 15. Jetsons only checks the 0xAAs
  (four times running), Domino's checks the pattern too.
* Every other packet: byte 15 = the command, as in AMH's ``sendData``
  (github.com/benheck/AMH). 0xFF = a plain exchange (the PIC wants the reply).
  The game's settings, audits and high scores live in the Propeller's
  EEPROM, 8192 longs, through 0x20/0x21/0x22 (AMH's ``Interpret``):
    0x20 write: bytes 0..3 address, 4..7 value -> reply[15] = 0x42
    0x21 read:  bytes 0..3 address, 14 = 7-bit tag -> reply = value LE in
                0..3, tag | 0x80 in 14, 0xAD in 15
    0x22 flush: reply = zeros
  The reply otherwise stays as it was: the Propeller only rewrites its
  out-buffer for these commands.
"""
PORT = "F"
SDO = 1 << 5
CLK = 1 << 12
SDI = 1 << 13
SYNC = 0xAA
EEPROM_LONGS = 8192


class PropLink:
    def __init__(self, pic, on_packet=None, eeprom=None):
        self.pic = pic
        # a fresh EEPROM reads 0xFF; the game then writes its defaults
        self.eeprom = eeprom if eeprom is not None else bytearray(b"\xFF" * EEPROM_LONGS * 4)
        self.on_packet = on_packet
        self.packets = []           # every packet the PIC sent, as bytes
        self.reply = bytes(16)      # clocked out during the next packet
        self._bits = 0
        self._buf = bytearray(16)
        pic.watch(PORT, self._lat)
        self._sdi(0)

    def _sdi(self, bit):
        if bit:
            self.pic.pins_in[PORT] |= SDI
        else:
            self.pic.pins_in[PORT] &= ~SDI

    def _lat(self, port, old, new):
        if port != PORT or not (new & CLK) or (old & CLK):
            return                                  # rising CLK edges only
        n, bit = divmod(self._bits, 8)
        if new & SDO:
            self._buf[n] |= 1 << bit
        # the PIC reads SDI after CLK falls: present this bit's reply now
        self._sdi((self.reply[n] >> bit) & 1)
        self._bits += 1
        if self._bits == 128:
            pkt = bytes(self._buf)
            self._bits, self._buf = 0, bytearray(16)
            self.packets.append(pkt)
            self.reply = self.answer(pkt)
            if self.on_packet:
                self.on_packet(pkt)

    def answer(self, pkt):
        """What the Propeller has ready for the PIC's next packet."""
        cmd = pkt[15]
        if pkt[0] == SYNC and cmd == ord("#"):
            return pkt[1:15] + b"\xAA\xAA"
        addr = (int.from_bytes(pkt[0:4], "little") % EEPROM_LONGS) * 4
        if cmd == 0x20:
            self.eeprom[addr:addr + 4] = pkt[4:8]
            return bytes(15) + b"\x42"
        if cmd == 0x21:
            return bytes(self.eeprom[addr:addr + 4]) + bytes(10) + bytes([(pkt[14] | 0x80) & 0xFF, 0xAD])
        if cmd == 0x22:
            return bytes(16)
        return self.reply
