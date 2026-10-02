"""PAD-320 feasibility probe: boot a pinHeck PRG on Unicorn MIPS32 LE.

Usage: python boot_probe.py <GAME_Vnnn.PRG> [instructions]
Prints what the game writes to UART1 (its serial monitor). Jetsons V004 and
Domino's V006 both reach "PROPELLER SYNC CHECK..." and wait there: the
Propeller side is not modelled yet.


Physical map (kseg0/kseg1 strip the top 3 bits):
  0x1D000000 program flash (PRG = flash from 0x9D000000)
  0x1FC00000 boot flash (empty: we jump straight to the app)
  0x00000000 RAM 128 KB
  0x1F800000 SFRs (MMIO, logged)
"""
import struct, sys, collections
from unicorn import *
from unicorn.mips_const import *

prg = open(sys.argv[1], 'rb').read()
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20_000_000

mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN)
mu.mem_map(0x1D000000, 0x80000)
mu.mem_write(0x1D000000, prg)
mu.mem_map(0x00000000, 0x20000)
mu.mem_map(0x1FC00000, 0x3000)

sfr = collections.defaultdict(int)
reads = collections.Counter()
uart = bytearray()
ticks = [0]

def mmio_read(uc, off, size, data):
    a = 0x1F800000 + off
    reads[a & ~3] += 1
    # UxSTA: TRMT=1 (bit 8), UTXBF=0 (bit 9) so writes never block
    if (a & 0xFFFFF1FF) in (0x1F806010, 0x1F806210, 0x1F806410, 0x1F806610, 0x1F806810, 0x1F806A10):
        return 0x100 | sfr[a]
    # OSCCON/PLL lock and similar "ready" bits: report set
    if a == 0x1F80F000:
        return sfr[a] | 0x20
    v = sfr[a & ~3]
    return v

def mmio_write(uc, off, size, value, data):
    a = 0x1F800000 + off
    base = a & ~0xF
    reg = a & 0xC
    # PIC32 CLR/SET/INV shadow registers at +4/+8/+C
    r = a & ~0xF
    if (a & 0xF) == 4: sfr[r] &= ~value
    elif (a & 0xF) == 8: sfr[r] |= value
    elif (a & 0xF) == 0xC: sfr[r] ^= value
    else: sfr[a] = value
    if (a & 0xFFFFF1FF) == 0x1F806020:      # UxTXREG
        uart.append(value & 0xFF)

mu.mmio_map(0x1F800000, 0x100000, mmio_read, None, mmio_write, None)

def intr(uc,intno,u):
    print('INTR',intno,'pc=%08x'%uc.reg_read(UC_MIPS_REG_PC)); uc.emu_stop()
mu.hook_add(UC_HOOK_INTR,intr)
def unm(uc,acc,addr,size,val,u):
    print('UNMAPPED acc=%d addr=%08x pc=%08x'%(acc,addr,uc.reg_read(UC_MIPS_REG_PC))); return False
mu.hook_add(UC_HOOK_MEM_UNMAPPED, unm)
# millis(): find delay()'s 'lw v0,off(gp); subu v0,v0,s1; sltu v0,v0,s0' and
# read gp from crt0 after a short run (the core-timer ISR is not modelled; we bump it)
MILLIS = None
for i in range(0x1000, len(prg) - 12, 4):
    w = struct.unpack('<3I', prg[i:i+12])
    if w[1] == 0x00511023 and w[2] == 0x0050102b and (w[0] >> 16) == 0x8f82:
        GPOFF = (w[0] & 0xffff) - (0x10000 if w[0] & 0x8000 else 0)
try: mu.emu_start(0x9D001000, 0x7FFFFFFC, count=2000)
except UcError: pass
MILLIS = (mu.reg_read(UC_MIPS_REG_GP) + GPOFF) & 0x1FFFFFFF
print('gp=%08x millis@%x' % (mu.reg_read(UC_MIPS_REG_GP), MILLIS))
pc = 0x9D001000
done = 0
import time; t0=time.time()
while done < limit:
    try:
        mu.emu_start(pc, 0x7FFFFFFC, count=80000)
    except UcError as e:
        p = mu.reg_read(UC_MIPS_REG_PC)
        if not (0x9D000000 <= p < 0x9D080000):
            print('stopped:', e, 'pc=%08x' % p); break
    pc = mu.reg_read(UC_MIPS_REG_PC)
    done += 80000
    m = struct.unpack('<I', mu.mem_read(MILLIS, 4))[0]
    mu.mem_write(MILLIS, struct.pack('<I', m + 1))
print('ran %d insns, %.1fs wall, millis=%d' % (done, time.time()-t0, struct.unpack('<I', mu.mem_read(MILLIS,4))[0]))
print('pc=%08x' % mu.reg_read(UC_MIPS_REG_PC))
print('UART (%d bytes):' % len(uart))
print(uart.decode('latin1'))
print('top SFR reads:', [(hex(a), n) for a, n in reads.most_common(12)])
