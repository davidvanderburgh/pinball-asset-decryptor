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

import ctypes
import struct

import numpy as np
from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
from capstone.arm import ARM_OP_REG, ARM_SFT_ASR
from unicorn import UC_HOOK_CODE
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
        self._calib = {}   # (scale, chan) -> (dom_mul_addr, S_reg, body_word_delta)

    def _install_hook(self, mul_addr):
        if mul_addr in self._hooked:
            return
        # The capture fires once per output sample; read the companding register
        # straight through the unicorn C API when available (the slow Python
        # reg_read wrapper is ~30% of recovery time -- see emulator.fast_reg_read),
        # else fall back to the portable mu.reg_read path.
        fast = self.emu.fast_reg_read
        if fast is not None:
            rr, uch = fast
            buf = ctypes.c_uint64(0); pbuf = ctypes.byref(buf)

            def cap(uc, address, size, ud):
                rr(uch, self._capreg, pbuf)
                self._cap.append(buf.value & 0xffff)
            self.mu.hook_add(UC_HOOK_CODE, cap, begin=mul_addr, end=mul_addr)
        else:
            def cap(eng):
                self._cap.append(eng.mu.reg_read(self._capreg))
            self.emu.add_hook(mul_addr, cap)
        self._hooked.add(mul_addr)

    def _drive_decode(self, p, cursor, body_u16):
        """Run one codec decode from ``cursor`` over the ``body_u16`` probe (no
        capture; the caller installs its own hooks).  The probe is written at the
        block's body base and a margin BEFORE it is filled with the probe's first
        value: the first output sample of a block reads body word ``base-1`` (the
        per-build body-word offset, see :meth:`_calibrate`), so without the margin
        that sample's keystream would be recovered from stale memory."""
        emu = self.emu; mu = self.mu
        decode_fn = emu.recover_entry(p)   # resolved audio slot (generic) / decode_fn (validated)
        arr = np.asarray(body_u16, dtype="<u2")
        R = max(0, 2 * cursor - 400)
        emu._ensure_body(_algn(R + 0x4000))
        pv = int(arr.ravel()[0]) & 0xffff if arr.size else 0
        fill = struct.pack("<H", pv)
        marg = min(R, 0x80)
        mu.mem_write(emu.BB + R - marg, fill * ((marg + 0x1000) // 2))
        if R == 0:
            # First block: base == BB, so the margin must sit BELOW the buffer
            # (delta=-1 keys read word base-1 for sample 0).  Without it that
            # sample's keystream was recovered from stale memory and the clip
            # in encode_sound had to discard enc[0] as garbage.
            emu.ensure_bb_margin()
            mu.mem_write(emu.BB - 0x80, fill * (0x80 // 2))
        mu.mem_write(emu.BB + R, arr.tobytes())
        mu.mem_write(emu.OBJ_VA, emu._build_obj(p))
        mu.mem_write(emu.VOICE_VA, emu._voice(1))
        emu.st["R"] = R; emu.st["k"] = R
        mu.mem_write(emu.VOICE_VA + 0xc, struct.pack("<I", cursor))
        mu.mem_write(emu.ACC, b"\x00" * 0x8000)
        mu.reg_write(UC_ARM_REG_R0, emu.VOICE_VA)
        mu.reg_write(UC_ARM_REG_R1, emu.ACC + 0x80)
        mu.reg_write(UC_ARM_REG_R2, VOL[1])
        mu.reg_write(UC_ARM_REG_SP, emu.STK + emu.STKSZ - 0x80000)
        mu.reg_write(UC_ARM_REG_LR, emu.LAND)
        mu.emu_start(decode_fn, emu.LAND, count=20_000_000)

    def _calibrate(self, p):
        """Resolve, per ``(scale, chan)``, the codec's DOMINANT companding site
        and its body-word offset ``delta`` (output sample ``i`` reads body word
        ``i + delta``).  Both vary by build:

          * ``_find_companding_all`` returns several companding sites in code
            order; on some builds the *first* one sits in a not-executed path and
            fires 0x (its captured keystream is empty/garbage).  Pick the site
            that actually fires (the most-fired).
          * the body pointer is set ``base + (voice[0x20]-1)`` words on some
            builds (delta = -1) and ``base`` on others (delta = 0), so a
            contiguous re-encode is one word off on the former.

        Two cheap probe decodes (one zeros, one single-marker), cached."""
        key = (p["scale"], p["chan"])
        if key in self._calib:
            return self._calib[key]
        emu = self.emu
        fn = emu.recover_entry(p)
        comps = _find_companding_all(emu.mu, fn)
        if not comps:
            raise RuntimeError("companding mul not found in 0x%x" % fn)
        # decode #1 (zeros): count fires + capture each site's S (= K there).
        caps = {a: [] for a, _ in comps}
        for a, reg in comps:
            def mk(addr, rr):
                def cb(eng):
                    caps[addr].append(eng.mu.reg_read(rr) & 0xffff)
                return cb
            emu.add_hook(a, mk(a, reg))
        self._drive_decode(p, 200, np.zeros(260, np.uint16))
        for a, _ in comps:
            emu.del_hook(a)
        dom_addr, sreg = max(comps, key=lambda ar: len(caps[ar[0]]))
        K = caps[dom_addr]
        # decode #2 (one body word = 0xFFFF): the affected sample reveals delta
        # (0xFFFF is rotate-invariant, so S^K == 0xFFFF exactly at that sample).
        q = 10
        marker = np.zeros(260, np.uint16); marker[q] = 0xFFFF
        capm = []
        emu.add_hook(dom_addr, lambda eng: capm.append(eng.mu.reg_read(sreg) & 0xffff))
        self._drive_decode(p, 200, marker)
        emu.del_hook(dom_addr)
        delta = 0
        for i in range(min(len(capm), len(K))):
            if (capm[i] ^ K[i]) & 0xffff == 0xffff:
                delta = q - i
                break
        self._calib[key] = (dom_addr, sreg, delta)
        return self._calib[key]

    def _decode_block_capture(self, p, cursor, body_u16):
        dom_addr, sreg, _delta = self._calibrate(p)
        self._capreg = sreg
        self._install_hook(dom_addr)
        self._cap = []
        self._drive_decode(p, cursor, body_u16)
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

    def encode_sound(self, p, target):
        """Full size-neutral mono body bytes that re-decode to ``target``.

        Returns ``(start_off, bytes)``: the byte window the hardware actually
        READS for this sound — ``body_off + 2*delta`` for ``delta < 0`` keys
        (output sample ``i`` reads body word ``i + delta``, so sample 0's word
        sits one word BELOW ``body_off`` on delta=-1 builds), ``body_off``
        otherwise.  Writing that whole window kills two real-machine clicks
        our emulated round-trips could never see (monkeybug, LZ cabinet
        recordings):

        * TAIL: the encode only covers the emitted range (length - BLOCK);
          the lead-out block past it can't be re-encoded, so the window is
          seeded from the ORIGINAL card bytes — raw zeros there decoded as a
          noise burst right after every replaced callout (lz_click.mp4).
        * HEAD: on delta=-1 keys the old fixed-at-``body_off`` window CLIPPED
          enc[0], leaving the stock word at ``body_off - 1`` — the machine
          decoded it as one full-amplitude stock sample right at the trigger,
          a per-slot tick in front of the replacement's fade-in
          (lz_click2.mp4: click follows the slot, never the content).  The
          shifted window writes that word.  Note it overlaps the LAST word of
          an adjacent predecessor's window (sounds are packed back-to-back):
          that word sits 200 samples into the predecessor's faded lead-out,
          where a one-sample change is inaudible — the loud, silence-adjacent
          trigger tick is the audible end of that trade."""
        length = p["length"]
        _a, _r, delta = self._calibrate(p)
        d = min(delta, 0)
        start = p["body_off"] + 2 * d
        tgt = np.asarray(target, np.int64)
        body = np.frombuffer(
            self.emu.mm[start:start + 2 * length], dtype="<u2").copy()
        for k in range((length + 199) // 200):
            g0 = 200 * k
            seg = tgt[g0:g0 + 200]
            if len(seg) == 0:
                break
            K, rb = self.recover_block(p, 200 + 200 * k, n=len(seg))
            m = len(K)
            enc, _ = self.encode_block(seg[:m], K, rb)
            lo = g0 + delta - d          # window-relative index of enc[0]
            s = max(0, -lo); e = min(m, length - lo)  # clip words out of range
            if s < e:
                body[lo + s:lo + e] = enc[s:e]
        return start, body.tobytes()


class StereoRecover:
    """Stereo (joint L/R) keystream recovery + analytic encode."""

    def __init__(self, emu):
        self.emu = emu
        self.mu = emu.mu
        emu.setup_decode()
        self.qmul = emu.qmul(2)
        self._cap = []
        self._hooked = set()
        self._calib = {}   # (scale, chan) -> body_frame_delta
        self._comps = {}   # render_fn -> [(mul_addr, S_reg), ...] (capstone cache)
        # (scale, chan) -> needs the third (0,1) probe.  The u1 rotate ``bR`` is
        # ≡0 on every observed build (verified across all 32 scales), so after the
        # first block of a scale confirms it, later blocks drop that probe (~1.5x).
        # A build that ever shows bR≠0 keeps the full 3-probe recovery for that
        # scale -- self-validating, never an assumption baked in.
        self._three_probe = {}

    def _hook(self, addr, reg):
        key = (addr, reg)
        if key in self._hooked:
            return
        # Fires twice per output frame (L + R companding sites); read the register
        # through the unicorn C API when available, else the portable path.
        fast = self.emu.fast_reg_read
        if fast is not None:
            rr, uch = fast
            buf = ctypes.c_uint64(0); pbuf = ctypes.byref(buf)

            def cap(uc, address, size, ud, _a=addr, _r=reg):
                rr(uch, _r, pbuf)
                self._cap.append((_a, buf.value & 0xffff))
            self.mu.hook_add(UC_HOOK_CODE, cap, begin=addr, end=addr)
        else:
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

    def _comps_for(self, render_fn):
        """Companding sites for ``render_fn``, cached.  The disassembly is
        identical every block (the firmware code never changes), so caching it
        avoids re-running capstone over 3 KB of code 3x per 200-sample block --
        which is ~70% of stereo re-encode time on a full-length song."""
        comps = self._comps.get(render_fn)
        if comps is None:
            comps = _find_companding_all(self.mu, render_fn, n=0xC00)
            if len(comps) < 2:
                raise RuntimeError("stereo render_fn must have >=2 companding pts")
            self._comps[render_fn] = comps
        return comps

    def _drive(self, p, cursor, body_bytes):
        emu = self.emu; mu = self.mu
        render_fn = emu.recover_entry(p)   # resolved audio slot (generic) / render_fn (validated)
        comps = self._comps_for(render_fn)
        for a, reg in comps:
            self._hook(a, reg)
        OBJ = emu._build_obj(p); VOICE = emu._voice(2)
        R = max(0, 4 * cursor - 800)
        emu._ensure_body(_algn(R + 0x8000))
        # mirror the first frame into a margin BEFORE the base: the first sample
        # of a block reads body frame ``base-1`` on builds with a -1 frame offset
        # (see :meth:`_calibrate`), so it must see the probe, not stale memory.
        first = body_bytes[:4] if len(body_bytes) >= 4 else b"\x00\x00\x00\x00"
        marg = min(R, 0x80)
        mu.mem_write(emu.BB + R - marg, first * (marg // 4))
        if R == 0:
            # First block: the margin must sit BELOW BB (see the mono driver).
            emu.ensure_bb_margin()
            mu.mem_write(emu.BB - 0x80, first * (0x80 // 4))
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

    def _calibrate(self, p):
        """Body-frame offset ``delta`` (output sample ``i`` reads body frame
        ``i + delta``), cached per ``(scale, chan)``.  Same -1/0 split as the
        mono path (see :meth:`GenRecover._calibrate`); the live L/R companding
        sites are already picked by fire count in :meth:`_split_lr`."""
        key = (p["scale"], p["chan"])
        if key in self._calib:
            return self._calib[key]
        nf = 60
        L0, _R0 = self._drive(p, 200, self._frame_body(nf, 0, 0))   # KL
        q = 10
        a = np.zeros(2 * nf, dtype="<u2"); a[2 * q] = 0xFFFF        # marker in u0
        Lm, _Rm = self._drive(p, 200, a.tobytes())
        delta = 0
        for i in range(min(len(L0), len(Lm))):
            if (int(Lm[i]) ^ int(L0[i])) & 0xffff == 0xffff:
                delta = q - i
                break
        self._calib[key] = delta
        return delta

    def encode_sound(self, p, targetL, targetR):
        """Full size-neutral stereo body bytes (interleaved u0/u1 per frame)
        that re-decode to ``(targetL, targetR)``.

        Returns ``(start_off, bytes)`` — the frame window the hardware reads,
        ``body_off + 4*delta`` on delta<0 keys so frame 0 (the trigger-time
        sample the machine plays FIRST) is actually written; see
        :meth:`GenRecover.encode_sound` for the head/tail click story (the 21
        delta=-1 sounds on LZ 1.22.0 are all stereo, so this path is where
        monkeybug's start-of-callout tick actually lived)."""
        length = p["length"]
        delta = self._calibrate(p)
        d = min(delta, 0)
        start = p["body_off"] + 4 * d
        L = np.asarray(targetL, np.int64); R = np.asarray(targetR, np.int64)
        body = np.frombuffer(
            self.emu.mm[start:start + 4 * length],
            dtype="<u2").copy()          # interleaved u0, u1
        for k in range((length + 199) // 200):
            g0 = 200 * k
            segL = L[g0:g0 + 200]
            if len(segL) == 0:
                break
            rec = self.recover_block(p, 200 + 200 * k, nf=len(segL))
            m = rec["m"]
            frame, _ = self.encode_block(L[g0:g0 + m], R[g0:g0 + m], rec)
            fr = frame.reshape(-1, 2)          # [m, 2] -> (u0, u1) per frame
            lo = g0 + delta - d          # window-relative index of frame 0
            s = max(0, -lo); e = min(m, length - lo)   # clip frames out of range
            if s < e:
                body[2 * (lo + s):2 * (lo + e)] = fr[s:e].ravel()
        return start, body.tobytes()

    def recover_block(self, p, cursor, nf=200):
        key = (p["scale"], p["chan"])
        # (0,0) -> KL, KR ; (1,0) -> rbL, aR.  These two are always needed.
        L0, R0 = self._drive(p, cursor, self._frame_body(nf + 4, 0, 0))   # KL, KR
        La, Ra = self._drive(p, cursor, self._frame_body(nf + 4, 1, 0))   # rbL, aR
        three = self._three_probe.get(key)
        if three is False:
            # bR confirmed ≡0 for this scale (first block did the full check);
            # skip the (0,1) probe that only recovers it.
            m = min(nf, len(L0), len(La))
            bR = np.zeros(m, np.int64)
        else:
            Lb, Rb = self._drive(p, cursor, self._frame_body(nf + 4, 0, 1))  # bR
            m = min(nf, len(L0), len(La), len(Lb))
            bR = _onehot_rb((Rb[:m] ^ R0[:m]) & 0xffff)
            if three is None:
                # First block of this scale: remember whether bR is ever nonzero
                # so the rest of the song (and later sounds of the same scale) can
                # drop the third probe when it's the universal all-zero case.
                self._three_probe[key] = bool(np.any(bR))
        KL, KR = L0[:m], R0[:m]
        rbL = _onehot_rb((La[:m] ^ KL) & 0xffff)
        aR = _onehot_rb((Ra[:m] ^ KR) & 0xffff)
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
