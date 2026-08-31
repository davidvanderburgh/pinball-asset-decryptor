"""Patch qemu-user's do_ioctl: generic passthrough for unknown ioctls.

The Spike 1 game is a static ARM binary, so its device ioctls can't be shimmed
via LD_PRELOAD — they have to reach a userspace device model (CUSE) through
qemu-user.  But stock qemu-user returns ENOTTY for any ioctl not in its
translation table, *without ever touching the host fd*, so CUSE devices never
see the game's device ioctls.

This rewrites the unknown-ioctl fallback in linux-user/syscall.c to do a
generic passthrough: scalar-arg ioctls (and legacy ioctls with no _IOC size)
pass the value straight to the host fd; _IOC-encoded ioctls bounce their sized
buffer to/from a host temp.  ARM and x86-64 share the asm-generic _IOC
encoding, so the cmd number needs no translation for these devices.

Idempotent; string-match based so it survives minor qemu-version drift.
Usage: python3 patch_qemu.py <qemu-src>/linux-user/syscall.c
"""
import sys

OLD = """        if (ie->target_cmd == 0) {
            qemu_log_mask(
                LOG_UNIMP, "Unsupported ioctl: cmd=0x%04lx\\n", (long)cmd);
            return -TARGET_ENOTTY;
        }"""

NEW = """        if (ie->target_cmd == 0) {
            /* PAD/spike1: I2C_RDWR (0x0707) — service the combined i2c
               transaction here.  qemu is where the nested guest i2c_msg
               buffers are addressable (CUSE can't do nested-pointer ioctls).
               Reads are filled from a virtual model (currently zeros — the
               per-chip content is TBD); set S1_I2C_LOG=1 to trace every
               transaction (slave addr / R|W / len / written bytes) so the
               board's i2c chips can be identified. */
            if (cmd == 0x0707) {
                /* virtual board EEPROM at slave 0x50: 64 KB, 16-bit
                   (big-endian) internal address.  A write msg's first two
                   bytes set the address; the rest are stored.  A read msg
                   returns from the current address.  Other slaves read 0xff. */
                static uint8_t _s1_ee[0x10000];
                static int _s1_ee_init;
                static char _s1_ee_path[512];
                static int _s1_ee_dirty;
                if (!_s1_ee_init) {
                    memset(_s1_ee, 0xff, sizeof _s1_ee);
                    /* persist the board EEPROM across runs (env S1_EE_FILE),
                       so first-boot provisioning survives the game's
                       init-then-restart. */
                    const char *_ep = getenv("S1_EE_FILE");
                    size_t _rd = 0;
                    if (_ep) {
                        strncpy(_s1_ee_path, _ep, sizeof _s1_ee_path - 1);
                        FILE *_ef = fopen(_ep, "rb");
                        if (_ef) {
                            _rd = fread(_s1_ee, 1, sizeof _s1_ee, _ef);
                            fclose(_ef);
                        }
                        fprintf(stderr,
                            "S1EE load '%s': read %zu bytes; [0x1ff8]=%02x%02x%02x%02x %02x%02x%02x%02x\\n",
                            _ep, _rd, _s1_ee[0x1ff8], _s1_ee[0x1ff9],
                            _s1_ee[0x1ffa], _s1_ee[0x1ffb], _s1_ee[0x1ffc],
                            _s1_ee[0x1ffd], _s1_ee[0x1ffe], _s1_ee[0x1fff]);
                    } else {
                        fprintf(stderr, "S1EE load: S1_EE_FILE not set\\n");
                    }
                    _s1_ee_init = 1;
                }
                int _log = getenv("S1_I2C_LOG") != NULL;
                uint32_t _hdr[2];
                void *_p = lock_user(VERIFY_READ, arg, 8, 1);
                if (!_p) { return -TARGET_EFAULT; }
                memcpy(_hdr, _p, 8);
                unlock_user(_p, arg, 0);
                unsigned int _nm = _hdr[1];
                if (_nm > 64) { _nm = 64; }
                /* the EEPROM address pointer persists across transactions (a
                   write sets it, a later read continues from it) — the game
                   does the address-write and the data-read as SEPARATE
                   I2C_RDWR calls, so this must be static, not per-call. */
                static unsigned int _off = 0;
                for (unsigned int _i = 0; _i < _nm; _i++) {
                    abi_long _ma = (abi_long)_hdr[0] + _i * 12;
                    uint8_t _mb[12];
                    _p = lock_user(VERIFY_READ, _ma, 12, 1);
                    if (!_p) { return -TARGET_EFAULT; }
                    memcpy(_mb, _p, 12);
                    unlock_user(_p, _ma, 0);
                    unsigned int _addr = _mb[0] | (_mb[1] << 8);
                    unsigned int _flags = _mb[2] | (_mb[3] << 8);
                    unsigned int _len = _mb[4] | (_mb[5] << 8);
                    abi_long _bufp = (abi_long)(_mb[8] | (_mb[9] << 8) |
                                     (_mb[10] << 16) | ((uint32_t)_mb[11] << 24));
                    if (_len > 0x1000) { _len = 0x1000; }
                    if (_flags & 1) {          /* I2C_M_RD */
                        if (_len) {
                            _p = lock_user(VERIFY_WRITE, _bufp, _len, 0);
                            if (_p) {
                                if (_addr == 0x50) {
                                    for (unsigned int _j = 0; _j < _len; _j++) {
                                        ((uint8_t *)_p)[_j] =
                                            _s1_ee[(_off + _j) & 0xffff];
                                    }
                                    _off = (_off + _len) & 0xffff;
                                } else {
                                    memset(_p, 0xff, _len);
                                }
                                unlock_user(_p, _bufp, _len);
                            }
                        }
                        if (_log) {
                            fprintf(stderr, "S1I2C RDWR RD addr=0x%02x len=%u\\n",
                                    _addr, _len);
                        }
                    } else {                   /* write */
                        uint8_t _wb[0x1000];
                        unsigned int _wl = _len < sizeof _wb ? _len : sizeof _wb;
                        if (_wl) {
                            _p = lock_user(VERIFY_READ, _bufp, _wl, 1);
                            if (_p) { memcpy(_wb, _p, _wl);
                                      unlock_user(_p, _bufp, 0); }
                        }
                        if (_addr == 0x50 && _wl >= 2) {
                            _off = ((unsigned int)_wb[0] << 8) | _wb[1];
                            for (unsigned int _j = 2; _j < _wl; _j++) {
                                _s1_ee[_off & 0xffff] = _wb[_j];
                                _off = (_off + 1) & 0xffff;
                            }
                            if (_wl > 2) { _s1_ee_dirty = 1; }
                        }
                        if (_log) {
                            unsigned int _pl = _wl < 8 ? _wl : 8;
                            fprintf(stderr, "S1I2C RDWR WR addr=0x%02x len=%u data=",
                                    _addr, _len);
                            for (unsigned int _j = 0; _j < _pl; _j++) {
                                fprintf(stderr, "%02x", _wb[_j]);
                            }
                            fprintf(stderr, "\\n");
                        }
                    }
                }
                if (_s1_ee_dirty && _s1_ee_path[0]) {   /* flush EEPROM */
                    FILE *_ef = fopen(_s1_ee_path, "wb");
                    if (_ef) {
                        if (fwrite(_s1_ee, 1, sizeof _s1_ee, _ef)) { /*ok*/ }
                        fclose(_ef);
                    }
                    _s1_ee_dirty = 0;
                }
                return _nm;                    /* success: msgs processed */
            }
            /* PAD/spike1: generic passthrough for ioctls not in the table, so
               userspace device models (CUSE) receive the guest's custom
               device ioctls instead of a blanket ENOTTY. */
            unsigned int _pad_sz = (((unsigned int)cmd) >> 16) & 0x3fff;
            unsigned int _pad_dir = (((unsigned int)cmd) >> 30) & 3;
            if (_pad_sz == 0 || _pad_dir == 0) {
                return get_errno(safe_ioctl(fd, cmd, arg));
            }
            if (_pad_sz > MAX_STRUCT_SIZE) {
                qemu_log_mask(LOG_UNIMP,
                    "Unsupported ioctl (too big): cmd=0x%04lx\\n", (long)cmd);
                return -TARGET_ENOTTY;
            }
            argptr = lock_user(VERIFY_READ, arg, _pad_sz, 1);
            if (!argptr) {
                return -TARGET_EFAULT;
            }
            memcpy(buf_temp, argptr, _pad_sz);
            unlock_user(argptr, arg, 0);
            ret = get_errno(safe_ioctl(fd, cmd, buf_temp));
            if (!is_error(ret) && (_pad_dir & 2)) {
                argptr = lock_user(VERIFY_WRITE, arg, _pad_sz, 0);
                if (!argptr) {
                    return -TARGET_EFAULT;
                }
                memcpy(argptr, buf_temp, _pad_sz);
                unlock_user(argptr, arg, _pad_sz);
            }
            return ret;
        }"""


# ---- patch 2: pass /proc/cpuinfo through to the bind-mounted fake ----------
# qemu-user intercepts /proc/cpuinfo and serves a *synthetic* cpuinfo for the
# emulated CPU.  For the default ARMv8 model that synthetic text has NO
# "Hardware:" line (qemu only emits it for arch < 8), so the game's platform
# probe — `cat /proc/cpuinfo | grep Hardware`, matched against "Freescale
# i.MX6" — sees nothing and mis-selects the AT91 hardware path, leaving the
# node bus dead.  We neutralise the fake by renaming the entry's match string
# (open_cpuinfo stays referenced, so no unused-function warning): /proc/cpuinfo
# then falls through to the normal open, serving our bind-mounted fake cpuinfo
# (which carries the real "Hardware : Freescale i.MX6 …" line).
OLD_CPU = '{ "/proc/cpuinfo", open_cpuinfo, is_proc },'
NEW_CPU = '{ "/proc/cpuinfo-spike1-passthrough", open_cpuinfo, is_proc },'


# ---- patch 3: swallow the game's fatal SIGFPE self-abort -------------------
# On the i.MX6 path the game sends SIGFPE (via tgkill/tkill) to a worker thread
# as an abort/fault path — but it never installs a SIGFPE handler, so under
# emulation the delivery just kills the whole process.  Gated on env
# S1_DROP_SIGFPE (default behaviour unchanged): when set, drop guest attempts
# to send SIGFPE and return success, so the game keeps running past the abort.
# Safe because a delivered SIGFPE could only ever crash this game.
OLD_SIG = """    case TARGET_NR_tkill:
        return get_errno(safe_tkill((int)arg1, target_to_host_signal(arg2)));

    case TARGET_NR_tgkill:
        return get_errno(safe_tgkill((int)arg1, (int)arg2,
                         target_to_host_signal(arg3)));"""

NEW_SIG = """    case TARGET_NR_tkill:
        if (arg2 == TARGET_SIGFPE && getenv("S1_DROP_SIGFPE")) {
            return 0;   /* PAD/spike1: swallow the game's fatal SIGFPE abort */
        }
        return get_errno(safe_tkill((int)arg1, target_to_host_signal(arg2)));

    case TARGET_NR_tgkill:
        if (arg3 == TARGET_SIGFPE && getenv("S1_DROP_SIGFPE")) {
            return 0;   /* PAD/spike1: swallow the game's fatal SIGFPE abort */
        }
        return get_errno(safe_tgkill((int)arg1, (int)arg2,
                         target_to_host_signal(arg3)));"""


# ---- patch 4: SPI_IOC_MESSAGE -> inject the CPU I/O expander inputs ---------
# The game reads its DEDICATED switches (start button, flippers, coin door) over
# an SPI I/O expander via CPUSPI_read_inputs -> doSpiTransaction ->
# ioctl(fd, SPI_IOC_MESSAGE(1), &spi_ioc_transfer) — NOT the node bus.  spidev's
# full-duplex transfer carries tx_buf/rx_buf as guest pointers INSIDE the
# transfer struct, so (exactly like I2C_RDWR above) CUSE can't reach them and the
# generic passthrough can't fill rx — the dedicated switches stay frozen and no
# start/flipper press is ever seen.  Service it here, where the guest buffers are
# addressable: fill each transfer's rx_buf from the injection file S1_CPUSW_FILE
# (raw input bytes the viewer/injector writes, in the CPU board's own active
# level).  With the env unset or the file absent it falls through to the generic
# passthrough — i.e. exactly the prior behaviour — so this only ever ADDS
# injection.  Inserted before the generic-passthrough comment, which patch 1
# guarantees is present.
_SPI_ANCHOR = """            /* PAD/spike1: generic passthrough for ioctls not in the table, so
               userspace device models (CUSE) receive the guest's custom
               device ioctls instead of a blanket ENOTTY. */"""

_SPI_BLOCK = """            /* PAD/spike1: SPI_IOC_MESSAGE — the CPU I/O expander transfer
               that carries the game's DEDICATED switches (start button,
               flippers, coin door).  Its tx/rx buffers are guest pointers
               inside the spi_ioc_transfer struct, so fill rx here from the
               injection file S1_CPUSW_FILE; unset/absent -> fall through. */
            if (((((unsigned int)cmd) >> 8) & 0xff) == 0x6b
                    && (((unsigned int)cmd) & 0xff) == 0) {
                const char *_sp = getenv("S1_CPUSW_FILE");
                FILE *_sf = _sp ? fopen(_sp, "rb") : NULL;
                if (_sf) {
                    uint8_t _in[64];
                    size_t _inlen = fread(_in, 1, sizeof _in, _sf);
                    fclose(_sf);
                    unsigned int _n = ((((unsigned int)cmd) >> 16) & 0x3fff) / 32;
                    unsigned int _total = 0;
                    for (unsigned int _i = 0; _i < _n; _i++) {
                        abi_long _ta = arg + (abi_long)(_i * 32);
                        uint8_t _tr[32];
                        void *_q = lock_user(VERIFY_READ, _ta, 32, 1);
                        if (!_q) { return -TARGET_EFAULT; }
                        memcpy(_tr, _q, 32);
                        unlock_user(_q, _ta, 0);
                        uint32_t _rx = _tr[8] | (_tr[9] << 8) | (_tr[10] << 16)
                                     | ((uint32_t)_tr[11] << 24);
                        uint32_t _len = _tr[16] | (_tr[17] << 8) | (_tr[18] << 16)
                                      | ((uint32_t)_tr[19] << 24);
                        _total += _len;
                        if (_rx && _len) {
                            void *_rp = lock_user(VERIFY_WRITE, (abi_long)_rx,
                                                  _len, 0);
                            if (_rp) {
                                for (uint32_t _j = 0; _j < _len; _j++) {
                                    ((uint8_t *)_rp)[_j] =
                                        _j < _inlen ? _in[_j] : 0x00;
                                }
                                unlock_user(_rp, (abi_long)_rx, _len);
                            }
                        }
                    }
                    return _total ? (abi_long)_total : 0;
                }
            }
""" + _SPI_ANCHOR


# ---- patch 7: glibc 2.41+ already defines struct sched_attr ----------------
# glibc 2.41 (Debian 13 / Ubuntu 25.04 era) exposes the kernel's struct
# sched_attr through <sched.h> -> <linux/sched/types.h>, so qemu 8.2.2's local
# copy in syscall.c is a redefinition and the build dies before it starts
# ("error: redefinition of 'struct sched_attr'").  qemu fixed this upstream
# after 8.2 the same way: keep the local copy only for older glibc.  The two
# layouts are identical field-for-field, so on new glibc the kernel header's
# definition serves the same code unchanged; non-glibc libcs keep qemu's copy
# (stock behaviour).
OLD_SCHED = """/* sched_attr is not defined in glibc */
struct sched_attr {
    uint32_t size;
    uint32_t sched_policy;
    uint64_t sched_flags;
    int32_t sched_nice;
    uint32_t sched_priority;
    uint64_t sched_runtime;
    uint64_t sched_deadline;
    uint64_t sched_period;
    uint32_t sched_util_min;
    uint32_t sched_util_max;
};"""

NEW_SCHED = """/* PAD/spike1: glibc 2.41+ defines struct sched_attr itself (via
   <linux/sched/types.h> from <sched.h>) with this exact layout, so keep
   qemu's local copy only where glibc doesn't provide one. */
#if !defined(__GLIBC__) || __GLIBC__ < 2 \\
        || (__GLIBC__ == 2 && __GLIBC_MINOR__ < 41)
/* sched_attr is not defined in glibc */
struct sched_attr {
    uint32_t size;
    uint32_t sched_policy;
    uint64_t sched_flags;
    int32_t sched_nice;
    uint32_t sched_priority;
    uint64_t sched_runtime;
    uint64_t sched_deadline;
    uint64_t sched_period;
    uint32_t sched_util_min;
    uint32_t sched_util_max;
};
#endif"""


# ---- patch 5: guest CPU-state dump on a fatal fault (signal.c) -------------
# On an uncaught guest signal, qemu-user prints only "uncaught target signal N"
# — not WHERE the game faulted.  Dumping the guest CPU state (PC + registers)
# to stderr makes any Spike 1 game crash immediately diagnosable from emu.log
# (this is exactly what found the WWE 1-arg-frequency-stub NULL deref).
_SIG_ANCHOR = """    trace_user_dump_core_and_abort(env, target_sig, host_sig);
    gdb_signalled(env, target_sig);"""
_SIG_BLOCK = """    trace_user_dump_core_and_abort(env, target_sig, host_sig);
    /* PAD/spike1: on a fatal fault, dump the guest CPU state (PC + regs) to
       stderr so the emulator log names exactly where the game crashed. */
    if (target_sig == TARGET_SIGSEGV || target_sig == TARGET_SIGBUS
            || target_sig == TARGET_SIGILL || target_sig == TARGET_SIGABRT) {
        fprintf(stderr, "PAD/spike1: FATAL guest signal %d — CPU state:\\n",
                target_sig);
        cpu_dump_state(cpu, stderr, 0);
    }
    gdb_signalled(env, target_sig);"""


# ---- patch 6: on-demand guest CPU-state dump via host SIGWINCH -------------
# The qemu-user gdb stub is too flaky on this build to interrupt a hung game
# and read its guest PC.  Instead: `kill -WINCH <tid>` (per-thread via tgkill)
# makes qemu print that thread's guest CPU state to stderr, twice —
#   * "live" immediately in the signal handler: accurate when the thread is
#     blocked in a syscall (regs were synced at syscall entry), possibly stale
#     when it is executing translated code (env only syncs at TB exits);
#   * "synced" at the next process_pending_signals() safepoint: accurate when
#     the thread is spinning in translated code (cpu_exit forces a TB exit),
#     never printed if the thread stays blocked in a syscall forever.
# The signal is never delivered to the guest.  SIGWINCH: qemu-user installs no
# handler for it by default (not a core-dump signal), the headless game
# neither uses nor receives it, and the rig runs detached from any tty.
_DBG_DECL_ANCHOR = """/* Fallback addresses into sigtramp page. */
abi_ulong default_sigreturn;
abi_ulong default_rt_sigreturn;"""
_DBG_DECL_BLOCK = _DBG_DECL_ANCHOR + """

/* PAD/spike1: thread whose synced CPU state the SIGWINCH debug dump wants
   printed at its next process_pending_signals() safepoint. */
static CPUState *s1_dump_cpu;"""

_DBG_HANDLER_ANCHOR = """    /*
     * Non-spoofed SIGSEGV and SIGBUS are synchronous, and need special
     * handling wrt signal blocking and unwinding.  Non-spoofed SIGILL,
     * SIGFPE, SIGTRAP are always host bugs.
     */
    if (info->si_code > 0) {"""
_DBG_HANDLER_BLOCK = """    /* PAD/spike1: SIGWINCH = on-demand guest CPU-state dump (see patch 6
       comment in patch_qemu.py).  Print the live state now, request a synced
       dump at the next safepoint, and never deliver to the guest. */
    if (host_sig == SIGWINCH) {
        fprintf(stderr,
                "PAD/spike1: DUMP (tid %d) live guest CPU state:\\n",
                qemu_get_thread_id());
        cpu_dump_state(cpu, stderr, 0);
        qatomic_set(&s1_dump_cpu, cpu);
        cpu_exit(cpu);
        return;
    }

""" + _DBG_HANDLER_ANCHOR

_DBG_INIT_ANCHOR = """        sigact_table[tsig - 1]._sa_handler = thand;
    }
}"""
_DBG_INIT_BLOCK = """        sigact_table[tsig - 1]._sa_handler = thand;
    }

    /* PAD/spike1: trap SIGWINCH as the on-demand debug-dump signal (see
       host_signal_handler); qemu leaves it untrapped by default. */
    sigaction(SIGWINCH, &act, NULL);
}"""

_DBG_SYNC_ANCHOR = """void process_pending_signals(CPUArchState *cpu_env)
{
    CPUState *cpu = env_cpu(cpu_env);
    int sig;
    TaskState *ts = cpu->opaque;
    sigset_t set;
    sigset_t *blocked_set;"""
_DBG_SYNC_BLOCK = _DBG_SYNC_ANCHOR + """

    /* PAD/spike1: synced dump requested by the SIGWINCH debug signal —
       guest state is consistent here. */
    if (qatomic_read(&s1_dump_cpu) == cpu) {
        qatomic_set(&s1_dump_cpu, NULL);
        fprintf(stderr,
                "PAD/spike1: DUMP (tid %d) synced guest CPU state:\\n",
                qemu_get_thread_id());
        cpu_dump_state(cpu, stderr, 0);
    }"""


def patch_signal(path):
    """Add the fatal-fault + on-demand CPU dumps to linux-user/signal.c."""
    src = open(path, encoding="utf-8").read()
    changed = False

    if "PAD/spike1: on a fatal fault" in src:
        print("crashdump patch: already patched")
    elif _SIG_ANCHOR not in src:
        print("CRASHDUMP PATCH ANCHOR NOT FOUND (qemu drift?)", file=sys.stderr)
        return 1
    else:
        src = src.replace(_SIG_ANCHOR, _SIG_BLOCK, 1)
        changed = True
        print("crashdump patch: applied")

    if "PAD/spike1: SIGWINCH = on-demand" in src:
        print("dumpsig patch: already patched")
    else:
        for name, anchor, block in (
            ("decl", _DBG_DECL_ANCHOR, _DBG_DECL_BLOCK),
            ("handler", _DBG_HANDLER_ANCHOR, _DBG_HANDLER_BLOCK),
            ("init", _DBG_INIT_ANCHOR, _DBG_INIT_BLOCK),
            ("sync", _DBG_SYNC_ANCHOR, _DBG_SYNC_BLOCK),
        ):
            if anchor not in src:
                print("DUMPSIG PATCH %s ANCHOR NOT FOUND (qemu drift?)" % name,
                      file=sys.stderr)
                return 1
            src = src.replace(anchor, block, 1)
        changed = True
        print("dumpsig patch: applied")

    if changed:
        open(path, "w", encoding="utf-8").write(src)
        print("wrote", path)
    return 0


def main():
    path = sys.argv[1]
    # signal.c gets only the crash-dump patch
    if path.endswith("signal.c"):
        return patch_signal(path)
    src = open(path, encoding="utf-8").read()
    changed = False

    if "PAD/spike1: generic passthrough" in src:
        print("ioctl patch: already patched")
    elif OLD not in src:
        print("IOCTL PATCH TARGET NOT FOUND (qemu version drift?)", file=sys.stderr)
        return 1
    else:
        src = src.replace(OLD, NEW, 1)
        changed = True
        print("ioctl patch: applied")

    if NEW_CPU in src:
        print("cpuinfo patch: already patched")
    elif OLD_CPU not in src:
        print("CPUINFO PATCH TARGET NOT FOUND (qemu version drift?)", file=sys.stderr)
        return 1
    else:
        src = src.replace(OLD_CPU, NEW_CPU, 1)
        changed = True
        print("cpuinfo patch: applied")

    if 'PAD/spike1: swallow the game' in src:
        print("sigfpe patch: already patched")
    elif OLD_SIG not in src:
        print("SIGFPE PATCH TARGET NOT FOUND (qemu version drift?)", file=sys.stderr)
        return 1
    else:
        src = src.replace(OLD_SIG, NEW_SIG, 1)
        changed = True
        print("sigfpe patch: applied")

    if "PAD/spike1: glibc 2.41+" in src:
        print("schedattr patch: already patched")
    elif OLD_SCHED not in src:
        print("SCHEDATTR PATCH TARGET NOT FOUND (qemu version drift?)",
              file=sys.stderr)
        return 1
    else:
        src = src.replace(OLD_SCHED, NEW_SCHED, 1)
        changed = True
        print("schedattr patch: applied")

    if "PAD/spike1: SPI_IOC_MESSAGE" in src:
        print("cpuspi patch: already patched")
    elif _SPI_ANCHOR not in src:
        print("CPUSPI PATCH ANCHOR NOT FOUND (ioctl patch missing?)", file=sys.stderr)
        return 1
    else:
        src = src.replace(_SPI_ANCHOR, _SPI_BLOCK, 1)
        changed = True
        print("cpuspi patch: applied")

    if changed:
        open(path, "w", encoding="utf-8").write(src)
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
