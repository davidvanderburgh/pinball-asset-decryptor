"""Analytic re-encode for the Spike 2 audio codec (mono + stereo, all scales).

The codec is a per-sample stream cipher whose mixer applies a linear, invertible
volume multiply ``G(S) = (QMUL * sxth(S)) >> 16``:

    MONO:    out[g] = G(ROR16(body16[g], rb_g) ^ K_g)
    STEREO:  L = G(ROR16(u0, rbL) ^ KL)
             R = G(ROR16(u0, aR) ^ ROR16(u1, bR) ^ KR)   (R joint in u0, u1)

We recover the exact per-position keystream/rotates by driving the firmware codec
on probe bodies and reading the value the companding ``mul; asr #0x10`` feeds
(via a hook installed right at that ``mul``).  Then encoding is analytic and
bit-exact, with no per-scale port:

    MONO:    body16[g] = ROL16(invG(target) ^ K_g, rb_g)       (2 decodes/block)
    STEREO:  u0 = ROL16(invG(L) ^ KL, rbL)                     (3 decodes/block)
             u1 = ROL16(invG(R) ^ KR ^ ROR16(u0, aR), bR)
"""

import struct

import numpy as np
from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
from capstone.arm import ARM_OP_REG, ARM_SFT_ASR
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,
                               UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                               UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
                               UC_ARM_REG_R11, UC_ARM_REG_R12, UC_ARM_REG_SP)

from .emulator import VOL, _algn

_md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
_md.detail = True

# the codec only ever reads its companding S out of one of these registers
_UCREG = {"r0": UC_ARM_REG_R0, "r1": UC_ARM_REG_R1, "r2": UC_ARM_REG_R2,
          "r3": UC_ARM_REG_R3, "r4": UC_ARM_REG_R4, "r5": UC_ARM_REG_R5,
          "r6": UC_ARM_REG_R6, "r7": UC_ARM_REG_R7, "r8": UC_ARM_REG_R8,
          "sb": UC_ARM_REG_R9, "sl": UC_ARM_REG_R10, "fp": UC_ARM_REG_R11,
          "ip": UC_ARM_REG_R12, "r9": UC_ARM_REG_R9, "r10": UC_ARM_REG_R10,
          "r11": UC_ARM_REG_R11, "r12": UC_ARM_REG_R12, "lr": UC_ARM_REG_LR,
          "r14": UC_ARM_REG_LR}


def _rorv(x, s):
    return ((x >> s) | (x << (16 - s))) & 0xffff


def _rolv(x, s):
    return ((x << s) | (x >> (16 - s))) & 0xffff


def _sxth_vec(x):
    x = x & 0xffff
    return np.where(x & 0x8000, x.astype(np.int64) - 0x10000, x).astype(np.int64)


def _onehot_rb(delta):
    """delta = ROR16(1, rb) (one-hot per element) -> rb = (16 - bitpos) & 15."""
    rb = np.empty(len(delta), np.int64)
    for j, d in enumerate(delta):
        d = int(d) & 0xffff
        pos = d.bit_length() - 1 if d else 0
        rb[j] = (16 - pos) & 0xf
    return rb


def _invG(target, qmul):
    """Nearest 16-bit S whose G(S)=(qmul*sxth(S))>>16 is closest to target."""
    t = np.asarray(target, dtype=np.int64)
    v0 = np.round(t.astype(np.float64) * 65536.0 / qmul).astype(np.int64)
    best = None; besterr = None
    for dv in (-2, -1, 0, 1, 2):
        v = np.clip(v0 + dv, -32768, 32767)
        g = (qmul * v) >> 16
        err = np.abs(g - t)
        if best is None:
            best, besterr = v, err
        else:
            take = err < besterr
            best = np.where(take, v, best)
            besterr = np.where(take, err, besterr)
    return (best & 0xffff), besterr


def _asr16_src_regs(ins):
    """Register operands this instruction arithmetic-shifts right by 16 -- the
    codec's ``>>16`` after the volume multiply.  Capstone tags the shifted
    operand the same way for BOTH the standalone ``asr rD, rS, #0x10`` (the rS
    operand carries ``asr #16``) and the folded ``add rD, rN, rM, asr #16`` (the
    rM operand carries it), so one rule covers both.  Older builds use the
    standalone form; some (e.g. Godzilla stereo) fold the shift into the
    consuming add, which the old standalone-only scan missed entirely."""
    return [ins.reg_name(o.reg) for o in ins.operands
            if o.type == ARM_OP_REG and o.shift.type == ARM_SFT_ASR
            and o.shift.value == 16]


def _find_companding_all(mu, fn_addr, n=0xC00):
    """All distinct ``(mul_addr, S_reg)`` companding points -- a ``mul`` of a
    sign-extended value whose product is then ``>>16`` (see _asr16_src_regs) --
    in code order.  Mono codecs have 1; stereo render_fns 2.  (Dead sites past
    the function epilogue may be picked up when the scan window overruns into a
    neighbouring fn, but they never execute, so the L/R split -- keyed on the
    addresses that actually fire -- ignores them.)"""
    insns = list(_md.disasm(bytes(mu.mem_read(fn_addr, n)), fn_addr))
    out = []; muls = []; last_sxth = None
    for ins in insns:
        if ins.mnemonic == "sxth":
            last_sxth = ins.op_str.split(",")[0].strip()
            continue
        if ins.mnemonic == "mul":
            regs = [t.strip() for t in ins.op_str.replace(",", " ").split()]
            muls.append((ins.address, regs[0], regs, last_sxth))
            continue
        seen = [o[0] for o in out]
        for src in _asr16_src_regs(ins):
            for addr, mdst, regs, sx in reversed(muls):
                if mdst == src and sx in regs and sx in _UCREG and addr not in seen:
                    out.append((addr, _UCREG[sx]))
                    break
    return out


def _find_companding(mu, fn_addr, n=0x600):
    comps = _find_companding_all(mu, fn_addr, n)
    if not comps:
        raise RuntimeError("companding mul not found in 0x%x" % fn_addr)
    return comps[0]


class GenRecover:
    """Mono keystream recovery + analytic encode, driven on a booted emulator."""

    def __init__(self, emu):
        self.emu = emu
        self.mu = emu.mu
        emu.setup_decode()
        self._cap = []
        self._capreg = None
        self._hooked = set()
        self.qmul = emu.qmul(1)

    def _install_hook(self, mul_addr):
        if mul_addr in self._hooked:
            return

        def cap(eng):
            self._cap.append(eng.mu.reg_read(self._capreg))
        self.emu.add_hook(mul_addr, cap)
        self._hooked.add(mul_addr)

    def _decode_block_capture(self, p, cursor, body_u16):
        emu = self.emu; mu = self.mu
        decode_fn = emu.recover_entry(p)   # resolved audio slot (generic) / decode_fn (validated)
        mul_addr, sreg = _find_companding(mu, decode_fn)
        self._capreg = sreg
        self._install_hook(mul_addr)
        OBJ = emu._build_obj(p); VOICE = emu._voice(1)
        R = max(0, 2 * cursor - 400)
        emu._ensure_body(_algn(R + 0x4000))
        mu.mem_write(emu.BB + R, b"\x00" * 0x1000)
        mu.mem_write(emu.BB + R, np.asarray(body_u16, dtype="<u2").tobytes())
        mu.mem_write(emu.OBJ_VA, OBJ); mu.mem_write(emu.VOICE_VA, VOICE)
        emu.st["R"] = R; emu.st["k"] = R
        mu.mem_write(emu.VOICE_VA + 0xc, struct.pack("<I", cursor))
        mu.mem_write(emu.ACC, b"\x00" * 0x8000)
        r1 = emu.ACC + 0x80
        mu.reg_write(UC_ARM_REG_R0, emu.VOICE_VA)
        mu.reg_write(UC_ARM_REG_R1, r1)
        mu.reg_write(UC_ARM_REG_R2, VOL[1])
        mu.reg_write(UC_ARM_REG_SP, emu.STK + emu.STKSZ - 0x80000)
        mu.reg_write(UC_ARM_REG_LR, emu.LAND)
        self._cap = []
        mu.emu_start(decode_fn, emu.LAND, count=20_000_000)
        return list(self._cap)

    def recover_block(self, p, cursor, n=200):
        """Return ``(K, rb)`` exact keystream for the block at ``cursor``."""
        zeros = np.zeros(n + 4, dtype=np.uint16)
        ones = np.ones(n + 4, dtype=np.uint16)
        s0 = self._decode_block_capture(p, cursor, zeros)   # S = K
        s1 = self._decode_block_capture(p, cursor, ones)    # S = ROR16(1, rb) ^ K
        m = min(n, len(s0), len(s1))
        K = np.array([v & 0xffff for v in s0[:m]], dtype=np.int64)
        S1 = np.array([v & 0xffff for v in s1[:m]], dtype=np.int64)
        rb = _onehot_rb((S1 ^ K) & 0xffff)
        return K, rb

    def encode_block(self, target, K, rb):
        S, err = _invG(target, self.qmul)
        body16 = _rolv((S ^ K.astype(np.int64)) & 0xffff,
                       rb.astype(np.int64)).astype(np.uint16)
        return body16, err


class StereoRecover:
    """Stereo (joint L/R) keystream recovery + analytic encode."""

    def __init__(self, emu):
        self.emu = emu
        self.mu = emu.mu
        emu.setup_decode()
        self.qmul = emu.qmul(2)
        self._cap = []
        self._hooked = set()

    def _hook(self, addr, reg):
        key = (addr, reg)
        if key in self._hooked:
            return

        def cap(eng, _a=addr, _r=reg):
            self._cap.append((_a, eng.mu.reg_read(_r) & 0xffff))
        self.emu.add_hook(addr, cap)
        self._hooked.add(key)

    @staticmethod
    def _frame_body(nf, u0, u1):
        a = np.empty(2 * nf, dtype="<u2")
        a[0::2] = u0; a[1::2] = u1
        return a.tobytes()

    def _split_lr(self, cap):
        from collections import Counter
        cnt = Counter(a for a, _ in cap)
        if len(cnt) < 2:
            v = np.array([x for _, x in cap], dtype=np.int64)
            return v, v
        top = [a for a, _ in cnt.most_common(2)]
        firstpos = {a: next(i for i, (aa, _) in enumerate(cap) if aa == a) for a in top}
        Laddr, Raddr = sorted(top, key=lambda a: firstpos[a])
        L = np.array([x for a, x in cap if a == Laddr], dtype=np.int64)
        R = np.array([x for a, x in cap if a == Raddr], dtype=np.int64)
        return L, R

    def _drive(self, p, cursor, body_bytes):
        emu = self.emu; mu = self.mu
        render_fn = emu.recover_entry(p)   # resolved audio slot (generic) / render_fn (validated)
        comps = _find_companding_all(mu, render_fn, n=0xC00)
        if len(comps) < 2:
            raise RuntimeError("stereo render_fn must have >=2 companding pts")
        for a, reg in comps:
            self._hook(a, reg)
        OBJ = emu._build_obj(p); VOICE = emu._voice(2)
        R = max(0, 4 * cursor - 800)
        emu._ensure_body(_algn(R + 0x8000))
        mu.mem_write(emu.BB + R, b"\x00" * 0x2000)
        mu.mem_write(emu.BB + R, body_bytes)
        mu.mem_write(emu.OBJ_VA, OBJ); mu.mem_write(emu.VOICE_VA, VOICE)
        emu.st["R"] = R; emu.st["k"] = R
        mu.mem_write(emu.VOICE_VA + 0xc, struct.pack("<I", cursor))
        mu.mem_write(emu.ACC, b"\x00" * 0x8000)
        r1 = emu.ACC + 0x80
        mu.reg_write(UC_ARM_REG_R0, emu.VOICE_VA)
        mu.reg_write(UC_ARM_REG_R1, r1)
        mu.reg_write(UC_ARM_REG_R2, VOL[2])
        mu.reg_write(UC_ARM_REG_SP, emu.STK + emu.STKSZ - 0x80000)
        mu.reg_write(UC_ARM_REG_LR, emu.LAND)
        self._cap = []
        mu.emu_start(render_fn, emu.LAND, count=30_000_000)
        return self._split_lr(self._cap)

    def recover_block(self, p, cursor, nf=200):
        L0, R0 = self._drive(p, cursor, self._frame_body(nf + 4, 0, 0))   # KL, KR
        La, Ra = self._drive(p, cursor, self._frame_body(nf + 4, 1, 0))   # rbL, aR
        Lb, Rb = self._drive(p, cursor, self._frame_body(nf + 4, 0, 1))   # bR
        m = min(nf, len(L0), len(La), len(Lb))
        KL, KR = L0[:m], R0[:m]
        rbL = _onehot_rb((La[:m] ^ KL) & 0xffff)
        aR = _onehot_rb((Ra[:m] ^ KR) & 0xffff)
        bR = _onehot_rb((Rb[:m] ^ KR) & 0xffff)
        return {"KL": KL, "rbL": rbL, "KR": KR, "aR": aR, "bR": bR, "m": m}

    def encode_block(self, targetL, targetR, rec):
        m = rec["m"]
        SL, eL = _invG(np.asarray(targetL)[:m], self.qmul)
        SR, eR = _invG(np.asarray(targetR)[:m], self.qmul)
        u0 = _rolv((SL ^ rec["KL"]) & 0xffff, rec["rbL"])
        u1 = _rolv((SR ^ rec["KR"] ^ _rorv(u0, rec["aR"])) & 0xffff, rec["bR"])
        frame = np.empty(2 * m, dtype="<u2")
        frame[0::2] = u0; frame[1::2] = u1
        return frame, np.maximum(eL, eR)
