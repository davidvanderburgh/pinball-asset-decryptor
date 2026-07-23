"""Decryption pipeline - orchestrates the 7-phase decryption process."""

import base64
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field

from . import config
from .resources import DECRYPT_C_SOURCE, ENCRYPT_C_SOURCE, STUB_C_SOURCE
from .executor import (CommandError, create_executor, find_usbipd,
                       _decode_output as _exec_decode_output,
                       _CREATE_FLAGS as _exec_create_flags)


# ---------------------------------------------------------------------------
# Developer crypto-capture shim (dongle extract only)
# ---------------------------------------------------------------------------
# Lives here (not in resources.py, which the regression check pins byte-equal
# to upstream) because it is a new, unified-app-only helper.  When a dongle
# extract runs with ``dev_capture`` set, this second LD_PRELOAD pass dumps the
# game's OWN decrypted asset-crypto routines so a developer can add dongle-free
# support for a title whose cipher isn't reverse-engineered yet (e.g. Sonic).
# It resolves the same functions the decrypt shim drives, then copies 8 KB of
# x86-64 code from each — reading byte-by-byte under a SIGSEGV guard so a read
# that runs off the end of .text can't crash the game.
DEV_CAPTURE_C_SOURCE = r"""
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <setjmp.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/syscall.h>

static sigjmp_buf g_jb;
static void on_fault(int s){ (void)s; siglongjmp(g_jb, 1); }

static void dump_region(const char *dir, const char *name, void *addr, size_t n){
    if(!addr) return;
    uint8_t *buf = (uint8_t*)malloc(n);
    if(!buf) return;
    struct sigaction sa, oldsegv, oldbus;
    memset(&sa, 0, sizeof sa); sa.sa_handler = on_fault; sigemptyset(&sa.sa_mask);
    sigaction(SIGSEGV, &sa, &oldsegv); sigaction(SIGBUS, &sa, &oldbus);
    size_t got = 0;
    if(sigsetjmp(g_jb, 1) == 0){
        for(; got < n; got++) buf[got] = ((volatile uint8_t*)addr)[got];
    }
    sigaction(SIGSEGV, &oldsegv, NULL); sigaction(SIGBUS, &oldbus, NULL);
    char path[4096]; snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "wb");
    if(f){ fwrite(buf, 1, got, f); fclose(f); }
    fprintf(stderr, "[capture] %s <- %p (%zu bytes)\n", name, addr, got);
    free(buf);
}

static volatile int g_cap_fired = 0;

/* Copy /proc/self/maps so a dev can recover function offsets even when a symbol
 * did not resolve (e.g. an envelope that keeps its crypto symbols internal). */
static void dump_maps(const char *dir){
    char p[4096]; snprintf(p, sizeof p, "%s/proc_self_maps.txt", dir);
    FILE *o = fopen(p, "w"); if(!o) return;
    FILE *m = fopen("/proc/self/maps", "r");
    if(m){
        char b[2048]; size_t k;
        while((k = fread(b,1,sizeof b,m)) > 0) fwrite(b,1,k,o);
        fclose(m);
    }
    fclose(o);
}

static void *cap_resolve(void *h, const char **names){
    for(int i=0; names[i]; i++){ void *p = dlsym(h, names[i]); if(p) return p; }
    return NULL;
}

/* One-shot capture: resolve the game's own crypto, open the dongle session,
 * dump 8 KB of each routine + the module map, exit.  Best-effort: writes the
 * manifest + maps even if a symbol is nil so a dongle session is never wasted. */
static void run_capture(const char *via){
    if(__sync_lock_test_and_set(&g_cap_fired, 1)) return;

    void *h = dlopen(NULL, RTLD_NOW);
    const char *dir = getenv("JJP_DEV_CAPTURE_DIR");
    if(!dir || !dir[0]) dir = "/tmp/jjp_dev_capture";
    mkdir(dir, 0755);

    const char *r64_n[]  = { "_Z13jcrypt_rand64v", NULL };
    const char *sc_n[]   = { "_Z27jcrypt_set_seeds_for_cryptoPKc", NULL };
    const char *dd_n[]   = { "_Z21dongle_decrypt_bufferPvj", NULL };
    const char *hash_n[] = { "_Z11hash_stringPKc", "_Z18jcrypt_hash_stringPKc", NULL };
    const char *init_n[] = { "_Z11dongle_initv", "_Z11dongle_initb",
        "_Z17dongle_initializev", "_Z14dongle_connectv", "_Z12dongle_loginv",
        "_Z10DongleInitv", "dongle_init", "dongle_initialize", NULL };

    void *rand64     = cap_resolve(h, r64_n);
    void *set_crypto = cap_resolve(h, sc_n);
    void *dongle_dec = cap_resolve(h, dd_n);
    void *hash_str   = cap_resolve(h, hash_n);
    void *dinit      = cap_resolve(h, init_n);
    if(dinit) ((int(*)(void))dinit)();

    fprintf(stderr, "[capture] hook via %s: rand64=%p set_crypto=%p "
            "dongle_dec=%p hash=%p\n", via, rand64, set_crypto, dongle_dec, hash_str);

    char mpath[4096]; snprintf(mpath, sizeof mpath, "%s/manifest.txt", dir);
    FILE *m = fopen(mpath, "w");
    if(m){
        fprintf(m, "JJP developer crypto capture\n");
        fprintf(m, "hook=%s\n", via);
        fprintf(m, "rand64=%p\nset_seeds_for_crypto=%p\n"
                   "dongle_decrypt_buffer=%p\nhash_string=%p\n",
                rand64, set_crypto, dongle_dec, hash_str);
        fprintf(m, "each *.bin holds up to 8192 raw bytes of x86-64 code from "
                   "that function pointer (disassemble to recover the cipher); "
                   "proc_self_maps.txt gives the module layout if a symbol was nil\n");
        fclose(m);
    }
    dump_maps(dir);
    dump_region(dir, "jcrypt_rand64.bin", rand64, 8192);
    dump_region(dir, "jcrypt_set_seeds_for_crypto.bin", set_crypto, 8192);
    dump_region(dir, "dongle_decrypt_buffer.bin", dongle_dec, 8192);
    dump_region(dir, "hash_string.bin", hash_str, 8192);
    fprintf(stderr, "[capture] DONE -> %s\n", dir);
    syscall(SYS_exit_group, 0);
}

/* Old engine first-call (Allegro) pre-empts the new-engine hooks below; the new
 * hooks only fire for a title (e.g. Sonic) that never calls al_install_system. */
int al_install_system(int version, int (*atexit_ptr)(void (*)(void))){
    (void)version; (void)atexit_ptr; run_capture("al_install_system"); return 0;
}
void *XOpenDisplay(const char *n){ (void)n; run_capture("XOpenDisplay"); return (void*)0; }
int FT_Init_FreeType(void *a){ (void)a; run_capture("FT_Init_FreeType"); return 0; }
void *pa_simple_new(const char *a, const char *b, int c, const char *d,
                    const char *e, const void *f, const void *g,
                    const void *i, int *j){
    (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)i;(void)j;
    run_capture("pa_simple_new"); return (void*)0;
}
void *pa_context_new(void *a, const char *b){ (void)a; (void)b;
    run_capture("pa_context_new"); return (void*)0; }
int ov_fopen(const char *a, void *b){ (void)a; (void)b;
    run_capture("ov_fopen"); return -1; }
int ov_open_callbacks(void *a, void *b, const char *c, long d, void *e){
    (void)a;(void)b;(void)c;(void)d;(void)e;
    run_capture("ov_open_callbacks"); return -1;
}
"""


# Engine-agnostic entry hooks for the DECRYPT shim (appended at compile time)
# ---------------------------------------------------------------------------
# resources.py DECRYPT_C_SOURCE is pinned byte-verbatim to upstream by the
# regression firewall (tests/verify_no_upstream_regression.py), and it hooks
# ONLY Allegro's al_install_system.  Titles rebuilt off Allegro (JJP Sonic runs
# on libX11/libpulse/libfreetype/libvorbis, with NO liballegro) never call it,
# so the shim never fired and a dongle extract produced nothing.  Rather than
# edit the pinned file, _phase_compile appends this snippet to the upstream
# source: it interposes the newer engines' first-init calls, drops a diagnostic
# breadcrumb (which hook + /proc/self/maps) so a hook that fires but can't
# resolve the crypto still yields intel, then re-uses the upstream
# al_install_system(0, 0) (which resolves the game's own crypto, opens the
# dongle session, decrypts, and exits).  al_install_system is an Allegro
# program's FIRST call, so old titles exit before any of these fire and their
# behaviour is unchanged; these only ever run for a non-Allegro title.
DECRYPT_ENGINE_HOOKS_C = r"""

extern int al_install_system(int, int (*)(void (*)(void)));

static volatile int g_engine_hook_fired = 0;

static void jjp_hook_diag(const char *via) {
    const char *od = getenv("JJP_OUTPUT_DIR");
    char p[4096];
    snprintf(p, sizeof p, "%s/jjp_hook_diag.txt", (od && od[0]) ? od : "/tmp");
    FILE *d = fopen(p, "a");
    if (d) {
        fprintf(d, "=== decrypt hook fired via %s ===\n", via);
        char exe[4096];
        ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
        if (n > 0) { exe[n] = '\0'; fprintf(d, "exe=%s\n", exe); }
        FILE *m = fopen("/proc/self/maps", "r");
        if (m) {
            char b[2048]; size_t k;
            fprintf(d, "--- /proc/self/maps ---\n");
            while ((k = fread(b, 1, sizeof b, m)) > 0) fwrite(b, 1, k, d);
            fclose(m);
        }
        fprintf(d, "\n");
        fclose(d);
    }
    fprintf(stderr, "[decrypt] engine hook fired via %s\n", via);
}

/* First engine hook the game hits wins: breadcrumb, then hand off to the
 * upstream al_install_system (resolve + dongle + decrypt + exit). */
static void jjp_engine_fire(const char *via) {
    if (__sync_lock_test_and_set(&g_engine_hook_fired, 1)) return;
    jjp_hook_diag(via);
    al_install_system(0, 0);
}

/* New engines' first init call.  We never invoke the real function (the handoff
 * exits), so these only need to match by NAME for the loader to interpose. */
void *XOpenDisplay(const char *n){ (void)n; jjp_engine_fire("XOpenDisplay"); return (void*)0; }
int FT_Init_FreeType(void *a){ (void)a; jjp_engine_fire("FT_Init_FreeType"); return 0; }
void *pa_simple_new(const char *a, const char *b, int c, const char *d,
                    const char *e, const void *f, const void *g,
                    const void *i, int *j){
    (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)i;(void)j;
    jjp_engine_fire("pa_simple_new"); return (void*)0;
}
void *pa_context_new(void *a, const char *b){ (void)a; (void)b;
    jjp_engine_fire("pa_context_new"); return (void*)0; }
int ov_fopen(const char *a, void *b){ (void)a; (void)b;
    jjp_engine_fire("ov_fopen"); return -1; }
int ov_open_callbacks(void *a, void *b, const char *c, long d, void *e){
    (void)a;(void)b;(void)c;(void)d;(void)e;
    jjp_engine_fire("ov_open_callbacks"); return -1;
}
"""


def _kill_process_tree(proc):
    """Kill *proc* and all of its descendants.

    ``run_host`` runs commands with ``shell=True``, so the real program is a
    *grandchild* of our Popen handle (Popen -> cmd.exe -> program).  Killing
    only the immediate child leaves the grandchild alive holding the stdout/
    stderr pipes open, so a follow-up ``communicate()`` blocks forever — a
    momentarily wedged WSL / PowerShell would silently hang the whole pipeline
    with no log output.  Kill the entire tree so the pipes close.
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
                creationflags=_exec_create_flags)
            return
        except Exception:
            pass
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except Exception:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _robust_run_host(args, timeout=60):
    """Timeout-safe replacement for ``CommandExecutor.run_host``.

    The upstream executor.py is a byte-verbatim lift (the regression firewall
    in tests/test_upstream_regression.py), so this fix lives here in the ported
    pipeline and is patched onto the executor instance rather than edited into
    executor.py.  Unlike ``subprocess.run(..., shell=True, timeout=...)`` — which
    on a timeout kills only the cmd.exe shell, then re-enters communicate() and
    deadlocks on the grandchild's still-open pipes — this kills the whole
    process tree and returns promptly.  Same ``(rc, stdout, stderr)`` contract.
    """
    popen_kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        creationflags=_exec_create_flags,
    )
    if sys.platform != "win32":
        # Own session/group so _kill_process_tree can killpg the tree.
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, **popen_kwargs)
    except FileNotFoundError:
        return -1, "", f"Command not found: {args[0] if args else '?'}"
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
        return -1, _exec_decode_output(out), f"Command timed out after {timeout}s"
    return proc.returncode, _exec_decode_output(out), _exec_decode_output(err)


def _robust_run(executor):
    """Return a tree-kill-hardened replacement for ``executor.run``.

    Same contract as ``CommandExecutor.run`` (returns stdout as a str; raises
    ``CommandError`` on a non-zero exit or a timeout), but built on
    ``Popen`` + ``communicate(timeout)`` + :func:`_kill_process_tree` instead of
    ``subprocess.run(timeout=...)``.  On a timeout ``subprocess.run`` kills only
    the immediate child (``wsl.exe`` / ``sudo`` / ``docker``) and then re-enters
    ``communicate()`` to reap it — which **deadlocks** on a grandchild still
    holding the stdout pipe, e.g. a momentarily wedged WSL such as a cold boot
    right after ``wsl --shutdown``.  That's the same failure
    :func:`_robust_run_host` fixes for the host commands; this closes it for the
    in-executor ``run`` path too.  It mattered because the extract's early
    diagnostics tool-probes (``_log_system_diagnostics``) and prerequisite
    checks go through ``run`` — so a cold WSL there hung the whole extract with
    no log output instead of timing out cleanly.

    Unknown executor types fall back to the original ``run`` unchanged.
    """
    cls = type(executor).__name__
    orig_run = executor.run

    def _argv(bash_cmd):
        if cls == "WslExecutor":
            return ["wsl", "-u", "root", "--", "bash", "-c", bash_cmd]
        if cls == "NativeExecutor":
            return [*executor._cmd_prefix(), bash_cmd]
        if cls == "DockerExecutor":
            if not getattr(executor, "_container_running", False):
                return None  # let orig_run raise the canonical "not running"
            from .executor import _DOCKER_CONTAINER
            return ["docker", "exec", _DOCKER_CONTAINER, "bash", "-c", bash_cmd]
        return None

    def _run(bash_cmd, timeout=120):
        argv = _argv(bash_cmd)
        if argv is None:
            return orig_run(bash_cmd, timeout=timeout)
        popen_kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_exec_create_flags)
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True  # own group for killpg
        try:
            proc = subprocess.Popen(argv, **popen_kwargs)
        except FileNotFoundError as e:
            raise CommandError(bash_cmd, -1, str(e)) from e
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            _kill_process_tree(proc)
            try:
                out, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                out, err = b"", b""
            raise CommandError(
                bash_cmd, -1, f"Command timed out after {timeout}s") from e
        out_s = (out or b"").decode("utf-8", errors="replace")
        err_s = (err or b"").decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise CommandError(bash_cmd, proc.returncode,
                               (err_s + out_s).strip())
        return out_s

    return _run


def _install_robust_run_host(executor):
    """Shadow *executor*'s run/run_host/run_win with tree-killing versions.

    Set on the instance (not the class) so the verbatim executor.py is left
    untouched.  Hardens both the host-command path (``run_host``/``run_win``)
    and the in-executor command path (``run``) so a momentarily wedged WSL
    can't deadlock either.  See :func:`_robust_run_host` / :func:`_robust_run`.
    """
    executor.run_host = _robust_run_host
    executor.run_win = _robust_run_host
    executor.run = _robust_run(executor)
    return executor


class _PreventSystemSleep:
    """Context manager that keeps the host awake during a long pipeline.

    macOS idle-sleep was extending Direct-SSD runs from ~30 min to
    2+ hours: subprocess pipes pause when the system sleeps and
    resume on wake, so the wall-clock duration silently includes
    however long the lid was shut.  Wrap the pipeline entry point
    in ``with _PreventSystemSleep(): ...`` and the host stays
    awake for the duration of the run only — sleep behaviour
    reverts on exit (or process death, since we use lifetime-tied
    mechanisms on every platform).

    Per-platform mechanism:

    * **macOS**: spawn ``caffeinate -dimsu -w <our pid>`` as a
      child process.  The ``-w`` makes caffeinate auto-exit when
      our PID does, so even if we crash without calling
      ``__exit__`` the assertion lifts.
    * **Windows**: ``SetThreadExecutionState`` with the
      CONTINUOUS / SYSTEM_REQUIRED / AWAYMODE_REQUIRED flags.
      Reverts when we clear the flag in ``__exit__``.
    * **Linux**: best-effort ``systemd-inhibit --what=idle:sleep``
      if available; no-op otherwise.

    Failure to install the assertion is non-fatal — the pipeline
    runs anyway, just at the user's mercy for sleep behaviour.
    """

    def __init__(self, reason="Pinball Asset Decryptor extraction"):
        self.reason = reason
        self._proc = None
        self._prev_state = None

    def __enter__(self):
        platform = sys.platform
        try:
            if platform == "darwin":
                # -d display, -i idle, -m disk, -s system, -u user-active.
                # -w PID makes caffeinate die when our process dies.
                self._proc = subprocess.Popen(
                    ["caffeinate", "-dimsu", "-w", str(os.getpid())],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif platform == "win32":
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_AWAYMODE_REQUIRED = 0x00000040
                flags = (ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                         | ES_AWAYMODE_REQUIRED)
                self._prev_state = (
                    ctypes.windll.kernel32.SetThreadExecutionState(
                        flags))
            elif platform.startswith("linux"):
                import shutil
                if shutil.which("systemd-inhibit"):
                    # systemd-inhibit holds the lock for the lifetime
                    # of its child; use a sleep-forever child that
                    # will be reaped when we terminate it.
                    self._proc = subprocess.Popen(
                        ["systemd-inhibit",
                         "--what=idle:sleep",
                         f"--why={self.reason}",
                         "sleep", "infinity"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
        except Exception:
            # Best-effort — never let sleep-prevention break the run.
            self._proc = None
            self._prev_state = None
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._prev_state is not None:
            try:
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS)
            except Exception:
                pass
            self._prev_state = None
        return False  # never swallow exceptions


def _find_native_debugfs():
    """Find a native debugfs binary on macOS (from Homebrew e2fsprogs).

    Returns the path to debugfs if available, or None.
    """
    # Homebrew ARM (Apple Silicon)
    brew_arm = "/opt/homebrew/opt/e2fsprogs/sbin/debugfs"
    if os.path.isfile(brew_arm):
        return brew_arm
    # Homebrew Intel
    brew_intel = "/usr/local/opt/e2fsprogs/sbin/debugfs"
    if os.path.isfile(brew_intel):
        return brew_intel
    import shutil
    path = shutil.which("debugfs")
    return path


def _find_project_file(filename):
    """Locate a file shipped with this plugin (e.g. partclone_to_raw.py).

    The file lives inside this package (plugins/jjp/) in source installs,
    and the frozen builds --add-data it to the same package-relative path,
    so the directory of this module is the authoritative location.  The
    parent-dir and Contents/Resources candidates are legacy layouts kept
    as fallbacks.  Uses realpath() to resolve symlinks so Docker
    bind-mounts see the real file, not a dangling symlink.
    """
    pkg_dir = os.path.dirname(os.path.realpath(__file__))
    candidate = os.path.join(pkg_dir, filename)
    if os.path.isfile(candidate):
        return os.path.realpath(candidate)
    # Legacy layout: file one level above the package
    parent = os.path.join(os.path.dirname(pkg_dir), filename)
    if os.path.isfile(parent):
        return os.path.realpath(parent)
    # Legacy macOS .app bundle layout: Contents/Resources/
    resources = os.path.join(pkg_dir, "..", "Resources", filename)
    if os.path.isfile(resources):
        return os.path.realpath(resources)
    return candidate  # fall back (caller checks isfile and reports)


def _stage_project_file(filename, cache_dir):
    """Copy a project file into the Docker cache directory.

    Docker Desktop on macOS only shares certain host directories by default
    (e.g. /Users, /tmp).  The .app bundle lives in /Applications which is
    NOT shared, so bind-mounting it fails.  Instead, copy the file into the
    cache dir that is already mounted as /tmp inside the container.
    Returns the container-side path (/tmp/<filename>).
    """
    import shutil
    src = _find_project_file(filename)
    if os.path.isfile(src):
        dst = os.path.join(cache_dir, filename)
        shutil.copy2(src, dst)
    return f"/tmp/{filename}"


# Python script deployed to WSL for standalone decryption.
# Placeholders are filled by StandaloneDecryptPipeline._phase_decrypt_standalone().
#
# Files are independent, so both the dongle-free filler-size scan and the
# decrypt+write loop fan out across all CPU cores with multiprocessing.
# WSL is Linux, so the pools use fork: worker functions inherit the module
# globals (MP, OUT_DIR, PREFIX, HAS_FL_DAT) set before the pool is created,
# without re-pickling them.
_DECRYPT_SCRIPT = r'''
import sys, os, struct, hashlib
import multiprocessing as _mp
sys.path.insert(0, "/tmp")
from jjp_crypto import decrypt_file, detect_filler_size, crc32_buf, xor_keystream, PRNG
from jjp_filelist import parse_fl_dat, detect_edata_prefix, FileEntry, write_fl_dat

HAS_FL_DAT = {has_fl_dat}
MP = "{mp}"
OUT_DIR = "{out_dir}"
EDATA_DIR = "{edata_dir}"
GAME_NAME = "{game_name}"
EXTRACT_GRAPHICS = {extract_graphics}
EXTRACT_SOUNDS = {extract_sounds}

# Assigned in main() before the decrypt pool is created; forked workers
# inherit it.
PREFIX = ""

try:
    N_WORKERS = max(1, len(os.sched_getaffinity(0)))
except (AttributeError, OSError):
    N_WORKERS = max(1, os.cpu_count() or 4)

# Force the 'fork' start method so workers inherit the module globals
# (MP, OUT_DIR, PREFIX, HAS_FL_DAT) and the top-level worker functions
# without re-pickling them.  Python 3.14 changes the Linux default to
# 'forkserver', which would not carry the runtime PREFIX over.
_MP_CTX = _mp.get_context("fork")


def _scan_one(task):
    """Detect filler size + encrypted CRC for one file (dongle-free scan)."""
    full_path, crypto_path = task
    try:
        with open(full_path, "rb") as f:
            enc_data = f.read()
    except OSError:
        return None
    if len(enc_data) < 8:
        return None
    filler_size = detect_filler_size(enc_data, crypto_path)
    if filler_size < 0 or len(enc_data) <= filler_size:
        return None
    return (crypto_path, filler_size, crc32_buf(enc_data))


def _decrypt_one(task):
    """Decrypt + write one file. Returns (status, info, crc_decrypted, md5).

    md5 is the MD5 of the decrypted bytes, computed here while the content
    is already in memory so the checksum phase never has to read every
    asset back off disk a second time.
    """
    crypto_path, filler_size = task
    enc_path = MP + crypto_path
    if not os.path.isfile(enc_path):
        return ("skip", crypto_path, 0, "")
    try:
        with open(enc_path, "rb") as f:
            enc_data = f.read()
        if len(enc_data) <= filler_size:
            return ("skip", crypto_path, 0, "")
        content = decrypt_file(enc_data, filler_size, crypto_path)
        rel = (crypto_path[len(PREFIX):]
               if PREFIX and crypto_path.startswith(PREFIX) else crypto_path)
        out_path = OUT_DIR + "/" + rel
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(content)
        crc = crc32_buf(content) if not HAS_FL_DAT else 0
        return ("ok", crypto_path, crc, hashlib.md5(content).hexdigest())
    except Exception as ex:
        return ("fail", crypto_path + ": " + str(ex), 0, "")


def main():
    global PREFIX

    if HAS_FL_DAT:
        entries = parse_fl_dat("/tmp/fl_decrypted.dat")
        PREFIX = detect_edata_prefix(entries)
    else:
        # Scan filesystem to build file list (dongle-free)
        print("Scanning edata directory...", flush=True)
        edata_root = EDATA_DIR
        path_prefix = edata_root[len(MP):]
        if not path_prefix.endswith("/"):
            path_prefix += "/"

        all_files = []
        for dirpath, dirnames, filenames in os.walk(edata_root):
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, edata_root)
                all_files.append((full, path_prefix + rel))

        print("TOTAL_FILES={{}}".format(len(all_files)), flush=True)
        print("Detecting filler sizes ({{}} workers)...".format(N_WORKERS),
              flush=True)

        entries = []
        scanned = 0
        total_scan = len(all_files)
        with _MP_CTX.Pool(N_WORKERS) as pool:
            for res in pool.imap_unordered(_scan_one, all_files, chunksize=16):
                scanned += 1
                if res is not None:
                    entries.append(FileEntry(
                        path=res[0], filler_size=res[1],
                        crc_encrypted=res[2], crc_decrypted=0,
                    ))
                if scanned % 500 == 0:
                    print("  Scanned {{}}/{{}}".format(scanned, total_scan),
                          flush=True)

        PREFIX = detect_edata_prefix(entries)
        print("Scan complete: {{}} files found".format(len(entries)),
              flush=True)

    # Filter entries by selected categories
    if not EXTRACT_GRAPHICS or not EXTRACT_SOUNDS:
        def _keep(e):
            rel = (e.path[len(PREFIX):]
                   if PREFIX and e.path.startswith(PREFIX) else e.path)
            if rel.startswith("graphics/"):
                return EXTRACT_GRAPHICS
            if rel.startswith("sound/"):
                return EXTRACT_SOUNDS
            return True  # keep anything else (e.g. config files)
        before = len(entries)
        entries = [e for e in entries if _keep(e)]
        if before != len(entries):
            print("Filtered to {{}}/{{}} files by category selection".format(
                len(entries), before), flush=True)

    total = len(entries)
    if total == 0:
        print("BATCH COMPLETE", flush=True)
        print("Total: 0  OK: 0  Failed: 0  Skipped: 0", flush=True)
        return

    if HAS_FL_DAT:
        print("TOTAL_FILES={{}}".format(total), flush=True)
    print("Decrypting ({{}} workers)...".format(N_WORKERS), flush=True)

    ok = fail = skip = 0
    # When generating fl_decrypted.dat we need the decrypted CRC keyed by
    # path, so we can rebuild the entry list in the original order afterwards
    # (imap_unordered returns results out of order).
    crc_by_path = {{}}
    # md5 of each decrypted file (md5sum format line), so the checksum phase
    # doesn't have to read every asset back off disk.
    ck_lines = []
    tasks = [(e.path, e.filler_size) for e in entries]
    done = 0
    with _MP_CTX.Pool(N_WORKERS) as pool:
        for status, info, crc, md5 in pool.imap_unordered(
                _decrypt_one, tasks, chunksize=8):
            done += 1
            if status == "ok":
                ok += 1
                if not HAS_FL_DAT:
                    crc_by_path[info] = crc
                rel = (info[len(PREFIX):]
                       if PREFIX and info.startswith(PREFIX) else info)
                ck_lines.append(md5 + "  ./" + rel)
            elif status == "skip":
                skip += 1
            else:
                print("[FAIL] {{}}".format(info), flush=True)
                fail += 1
            if done % 100 == 0 or done == total:
                print("Progress: {{}} (ok={{}} fail={{}} skip={{}})".format(
                    done, ok, fail, skip), flush=True)

    # Hand the edata checksums to the host so the checksum phase only has to
    # hash the (far fewer) non-edata system files.  Written to a per-run
    # sidecar; the host merges it into .checksums.md5 and deletes it.
    ck_path = OUT_DIR + "/.checksums.edata.md5"
    with open(ck_path, "w") as ckf:
        if ck_lines:
            ckf.write("\n".join(ck_lines) + "\n")
    print("Wrote edata checksums: {{}} entries".format(len(ck_lines)),
          flush=True)

    # Save generated fl_decrypted.dat if we scanned
    if not HAS_FL_DAT and crc_by_path:
        computed_entries = [
            FileEntry(path=e.path, filler_size=e.filler_size,
                      crc_encrypted=e.crc_encrypted,
                      crc_decrypted=crc_by_path[e.path])
            for e in entries if e.path in crc_by_path
        ]
        fl_out = OUT_DIR + "/fl_decrypted.dat"
        write_fl_dat(computed_entries, fl_out)
        print("Generated fl_decrypted.dat with {{}} entries".format(
            len(computed_entries)), flush=True)

    print("BATCH COMPLETE", flush=True)
    print("Total: {{}}  OK: {{}}  Failed: {{}}  Skipped: {{}}".format(
        ok + fail + skip, ok, fail, skip), flush=True)


if __name__ == "__main__":
    main()
'''


_ENOSPC = "No space left on device"

# partclone's last reported percentage has to reach this before we accept the
# restore as complete.  It reports in whole percents and the final tick can be
# swallowed by the stream, so this sits just under 100 rather than at it.
_RESTORE_COMPLETE_PCT = 99


def _with_disk_full_hint(message):
    """Append a "how to fix it" pointer when *message* is an out-of-space error.

    The staging area lives inside the helper Linux environment (WSL on
    Windows, Docker on macOS), whose virtual disk is capped independently of
    the host drive — so users see "No space left on device" while their own
    disk shows hundreds of GB free.  Without a pointer to the actual knob the
    error reads as nonsense.
    """
    if _ENOSPC not in message:
        return message
    if sys.platform == "win32":
        return (message
                + "\n\nWSL's virtual disk is full — it is separate from your "
                  "Windows drive, so Windows can show plenty of free space "
                  "while WSL has none. To give it more room, click the "
                  "⚙ settings button (top right) → \"Manage disk "
                  "space…\" → \"Resize WSL disk…\", then run "
                  "this again.")
    return (message
            + "\n\nThe helper Linux environment (Docker) has run out of disk "
              "space — its virtual disk is separate from your drive. Increase "
              "the virtual disk limit in Docker Desktop (Settings → "
              "Resources) or free up space in it, then run this again.")


class PipelineError(Exception):
    """User-friendly pipeline error with phase context."""
    def __init__(self, phase, message):
        self.phase = phase
        super().__init__(f"[{phase}] {message}")


class DecryptionPipeline:
    """Runs the full decryption workflow across 7 phases.

    Callbacks:
        log_cb(text, level)       - emit a log line ("info", "error", "success")
        phase_cb(phase_index)     - current phase changed (0-6)
        progress_cb(current, total, desc) - progress update
        done_cb(success, summary) - pipeline finished
    """

    def __init__(self, image_path, output_path, log_cb, phase_cb, progress_cb, done_cb):
        self.image_path = image_path
        self.output_path = output_path
        self.log = log_cb
        self.log_link = lambda text, url: None  # optional; set by caller
        self.on_phase = phase_cb
        self.on_progress = progress_cb
        self.on_done = done_cb

        self.executor = _install_robust_run_host(create_executor())
        self.mount_point = None
        self.game_name = None
        self.cancelled = False
        self._succeeded = False
        self._bind_mounted = []
        self._iso_mount = None      # temp mount for ISO
        self._iso_mounted = False   # True if ISO was loop-mounted (vs xorriso)
        self._raw_img_path = None   # extracted raw ext4 (cached between runs)
        # When True, a dongle extract also dumps the game's decrypted crypto
        # routines for the developer (see _phase_dev_capture).  Set by the
        # manufacturer's make_dongle_extract_pipeline factory.
        self.dev_capture = False

    def cancel(self):
        """Request cancellation. Safe to call from any thread."""
        self.cancelled = True
        self.executor.kill()

    def _check_cancel(self):
        if self.cancelled:
            raise PipelineError("Cancelled", "Operation cancelled by user.")

    def _timed(self, label, phase_fn):
        """Run a phase and log its wall-clock duration — field reports of
        "it took forever" need to say WHICH phase ate the time."""
        t0 = time.monotonic()
        phase_fn()
        dt = int(time.monotonic() - t0)
        if dt >= 5:
            self.log(f"[{label}] phase took {dt // 60}m {dt % 60:02d}s", "info")

    def _generate_checksums(self, wsl_out=None):
        """Write .checksums.md5 for asset tracking (host-side, parallel).

        Hashing runs natively over the output folder rather than via md5sum
        over the WSL 9p bridge (slow both ways), and fans out across a thread
        pool.  When the decrypt phase pre-computed the edata files' MD5s
        (it has the decrypted bytes in memory anyway), those are merged in
        directly so this phase only reads the far fewer non-edata system
        files back off disk.

        *wsl_out* is accepted for caller compatibility but unused — the output
        folder is always host-accessible (``self.output_path``).
        """
        self.log("Generating checksums for asset tracking...", "info")
        try:
            self._write_checksums_parallel(self.output_path)
            self.log("Checksums saved to .checksums.md5 in output folder.",
                     "success")
        except OSError as e:
            self.log(f"Warning: Could not generate checksums ({e}). "
                     "Asset modification tracking will not be available.",
                     "info")

    def _write_checksums_parallel(self, out_dir):
        """Hash *out_dir* into .checksums.md5 (md5sum format), in parallel.

        Merges a per-run ``.checksums.edata.md5`` sidecar (written by the
        decrypt workers) when present, so pre-hashed edata files are not read
        again.  ``.checksums.md5`` is (re)written fresh and last, so its mtime
        stays newest for the revert fast-path in ``core.checksums``.
        """
        import hashlib
        from concurrent.futures import ThreadPoolExecutor, as_completed

        checksum_file = os.path.join(out_dir, ".checksums.md5")
        partial = os.path.join(out_dir, ".checksums.edata.md5")

        # md5sum-style line we both emit and parse: "<32 hex>  ./<rel>".
        line_re = re.compile(r'^([a-f0-9]{32})\s+\*?\./(.+)$')

        covered = set()
        prehashed_lines = []
        if getattr(self, "_edata_checksum_partial", False) \
                and os.path.isfile(partial):
            with open(partial, "r", encoding="utf-8", errors="replace") as pf:
                for line in pf:
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    prehashed_lines.append(line)
                    m = line_re.match(line)
                    if m:
                        covered.add(m.group(2))

        # Everything not already hashed gets a native host-side md5 here.
        skip_names = {".checksums.md5", ".checksums.edata.md5",
                      "fl_decrypted.dat"}
        to_hash = []  # (rel, abspath)
        for dirpath, _dn, filenames in os.walk(out_dir):
            for fn in filenames:
                if fn.startswith(".") or fn in skip_names \
                        or fn.endswith(".img"):
                    continue
                ap = os.path.join(dirpath, fn)
                rel = os.path.relpath(ap, out_dir).replace(os.sep, "/")
                if rel not in covered:
                    to_hash.append((rel, ap))

        total = len(prehashed_lines) + len(to_hash)
        self.on_progress(0, total, "Checksums...")

        def _md5(item):
            rel, ap = item
            try:
                h = hashlib.md5()
                with open(ap, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                return rel, h.hexdigest()
            except OSError:
                return rel, None  # unreadable -> skip (match md5sum tolerance)

        n_workers = min(16, max(1, os.cpu_count() or 4))
        done = len(prehashed_lines)
        with open(checksum_file, "w", encoding="utf-8") as out:
            if prehashed_lines:
                out.write("\n".join(prehashed_lines) + "\n")
            if to_hash:
                with ThreadPoolExecutor(max_workers=n_workers) as ex:
                    futs = [ex.submit(_md5, it) for it in to_hash]
                    for fut in as_completed(futs):
                        rel, md5 = fut.result()
                        if md5 is not None:
                            out.write("{}  ./{}\n".format(md5, rel))
                        done += 1
                        if done % 200 == 0 or done == total:
                            self.on_progress(done, total,
                                             f"Checksums: {done}/{total}")
                            if self.cancelled:
                                for f in futs:
                                    f.cancel()
                                raise PipelineError(
                                    "Cancelled", "Operation cancelled by user.")
        self.on_progress(total, total, "Checksums complete")

        # Consume the per-run sidecar so a later run can't merge a stale one.
        if prehashed_lines or os.path.isfile(partial):
            try:
                os.remove(partial)
            except OSError:
                pass

    def _log_system_diagnostics(self):
        """Log system/environment info for remote diagnostics.

        Each line is logged the moment it's gathered rather than buffered and
        flushed at the end, so if a probe stalls (e.g. a momentarily wedged
        WSL) the log still shows everything up to it instead of going silent —
        the difference between "hung at the WSL distro probe" and a blank log.
        """
        from pinball_decryptor import __version__ as _app_version

        def _clean_utf16(text):
            """Strip UTF-16 null bytes that WSL commands sometimes produce."""
            return text.replace("\x00", "")

        self.log("--- System Diagnostics ---", "info")
        self.log(f"Pinball Asset Decryptor v{_app_version}", "info")
        self.log(f"Python {sys.version.split()[0]}", "info")

        # Host OS
        if sys.platform == "win32":
            try:
                rc, out, _ = self.executor.run_host(
                    "powershell -NoProfile -Command "
                    '"(Get-CimInstance Win32_OperatingSystem).Caption '
                    "+ ' (build ' + "
                    "[System.Environment]::OSVersion.Version.Build + ')'\"",
                    timeout=10)
                out = _clean_utf16(out)
                if rc == 0 and out.strip():
                    self.log(f"Windows: {out.strip()}", "info")
            except Exception:
                self.log("Windows: (could not detect version)", "info")
        elif sys.platform == "darwin":
            try:
                rc, out, _ = self.executor.run_host(
                    "sw_vers -productVersion", timeout=5)
                if rc == 0 and out.strip():
                    self.log(f"macOS: {out.strip()}", "info")
            except Exception:
                pass

        # WSL info (Windows only)
        if sys.platform == "win32":
            # WSL version + kernel
            try:
                rc, out, _ = self.executor.run_host(
                    "wsl --version", timeout=10)
                out = _clean_utf16(out)
                if rc == 0 and out.strip():
                    for wl in out.strip().splitlines()[:3]:
                        wl = wl.strip()
                        if wl:
                            self.log(f"  {wl}", "info")
            except Exception:
                self.log("  WSL: (could not detect)", "info")

            # WSL distro
            try:
                rc, out, _ = self.executor.run_host(
                    "wsl -l -v", timeout=10)
                out = _clean_utf16(out)
                if rc == 0 and out.strip():
                    for dl in out.strip().splitlines():
                        dl = dl.strip()
                        if dl and "NAME" not in dl.upper()[:10]:
                            self.log(f"  {dl}", "info")
            except Exception:
                pass

        # Docker info (macOS only)
        if sys.platform == "darwin":
            try:
                rc, out, _ = self.executor.run_host(
                    "docker --version", timeout=5)
                if rc == 0 and out.strip():
                    self.log(f"  Docker: {out.strip()}", "info")
            except Exception:
                self.log("  Docker: (could not detect)", "info")

            # Docker Desktop VM resources vs the host — an underprovisioned
            # VM (the default is often half the cores) directly throttles
            # the compress/decompress phases.
            try:
                rc, out, _ = self.executor.run_host(
                    "docker info --format '{{.NCPU}} {{.MemTotal}}'",
                    timeout=10)
                rc2, host_cpus, _ = self.executor.run_host(
                    "sysctl -n hw.ncpu", timeout=5)
                if rc == 0 and rc2 == 0 and out.strip():
                    vm_cpus, vm_mem = out.split()
                    vm_cpus, host_cpus = int(vm_cpus), int(host_cpus.strip())
                    vm_gb = int(vm_mem) / (1024 ** 3)
                    self.log(
                        f"  Docker VM: {vm_cpus} of {host_cpus} host CPUs, "
                        f"{vm_gb:.1f} GB RAM", "info")
                    if vm_cpus < host_cpus:
                        self.log(
                            f"  Tip: raising Docker Desktop's CPU limit "
                            f"(Settings > Resources) to {host_cpus} CPUs "
                            f"speeds up ISO builds.", "info")
            except Exception:
                pass

        # Tool versions inside executor (WSL, Docker, or native)
        # Skip tool checks if Docker container isn't running yet —
        # tools are inside the container and can't be queried from the host.
        from .executor import DockerExecutor
        if isinstance(self.executor, DockerExecutor) and \
                not self.executor._container_running:
            self.log("  (tools available inside Docker container)", "info")
        else:
            tools = [
                ("xorriso", "xorriso --version 2>&1 | head -1"),
                ("partclone", "partclone.restore --version 2>&1 | head -1"),
                ("pigz", "pigz --version 2>&1 | head -1"),
                ("e2fsck", "e2fsck -V 2>&1 | head -1"),
                ("base64", "base64 --version 2>&1 | head -1"),
                ("gzip", "gzip --version 2>&1 | head -1"),
                ("ffmpeg", "ffmpeg -version 2>&1 | head -1"),
            ]
            for name, cmd in tools:
                try:
                    out = self.executor.run(cmd, timeout=5).strip()
                    if out:
                        self.log(f"  {name}: {out}", "info")
                    else:
                        self.log(f"  {name}: (installed, no version)", "info")
                except Exception:
                    self.log(f"  {name}: NOT FOUND", "info")

        # Disk space on /tmp (where executor work happens)
        try:
            out = self.executor.run(
                "df -h /tmp 2>/dev/null | tail -1",
                timeout=5).strip()
            if out:
                parts = out.split()
                free = parts[3] if len(parts) >= 4 else out
                self.log(f"  /tmp free space: {free}", "info")
        except Exception:
            pass

        self.log("--------------------------", "info")

    def _is_iso(self):
        """Check if the input file is an ISO image."""
        return self.image_path.lower().endswith(".iso")

    def run(self):
        """Execute the full pipeline. Call from a background thread."""
        cleanup_phase = len(config.PHASES) - 1  # last phase is always Cleanup
        try:
            # Verify paths are accessible from the executor
            for label, path in [("Game image", self.image_path),
                                ("Output folder", self.output_path)]:
                ok, msg = self.executor.check_path_accessible(path)
                if not ok:
                    raise PipelineError("Extract", f"{label} path error:\n{msg}")

            self.on_phase(0)  # Extract
            self._phase_extract()
            self._check_cancel()

            self.on_phase(1)  # Mount
            self._phase_mount()
            self._check_cancel()

            self.on_phase(2)  # Chroot
            self._phase_chroot()
            self._check_cancel()

            self.on_phase(3)  # Dongle
            self._phase_dongle()
            self._check_cancel()

            self.on_phase(4)  # Compile
            self._phase_compile()
            self._check_cancel()

            self.on_phase(5)  # Decrypt
            self._phase_decrypt()
            self._check_cancel()

            # Optional developer crypto capture (dongle extract only) — never
            # fails the run; the assets are already decrypted at this point.
            self._phase_dev_capture()

            self.on_phase(6)  # Copy
            self._phase_copy()

            self._succeeded = True
            self.on_phase(cleanup_phase)  # Cleanup
            self._phase_cleanup()
            self.on_done(True, f"Decryption complete! Files saved to:\n{self.output_path}")

        except PipelineError as e:
            self.log(str(e), "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup()
            self.on_done(False, str(e))
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup()
            self.on_done(False, f"Unexpected error: {e}")

    # --- Phase 0: Extract (ISO → raw ext4) ---

    def _raw_img_cache_path(self):
        """Deterministic cache path for the extracted raw image, based on ISO filename.

        Uses /var/tmp instead of /tmp because WSL2's systemd-tmpfiles-clean
        can delete large files from /tmp while they are still loop-mounted,
        causing e2fsck / partclone to fail with 'No such file or directory'.
        """
        import os
        basename = os.path.splitext(os.path.basename(self.image_path))[0]
        # Sanitize for use as a Linux filename
        safe = re.sub(r'[^a-zA-Z0-9._-]', '_', basename)
        return f"/var/tmp/jjp_raw_{safe}.img"

    def _phase_extract(self):
        if not self._is_iso():
            self.log("Input is a raw image, skipping extraction.", "info")
            return

        self._raw_img_path = self._raw_img_cache_path()

        # Delete any stale image from a previous run
        try:
            self.executor.run(
                f"rm -f '{self._raw_img_path}' 2>/dev/null; true",
                timeout=10,
            )
        except CommandError:
            pass

        self.log("Extracting ext4 filesystem from ISO...", "info")
        wsl_iso = self.executor.to_exec_path(self.image_path)
        tag = uuid.uuid4().hex[:8]
        self._iso_mount = f"/var/tmp/jjp_iso_{tag}"

        # Mount the ISO (or extract via xorriso if loop devices fail)
        self._iso_mounted = False
        try:
            self.executor.run(f"mkdir -p {self._iso_mount}", timeout=10)
            self.executor.run(
                f"mount -o loop,ro '{wsl_iso}' {self._iso_mount}",
                timeout=config.MOUNT_TIMEOUT,
            )
            self._iso_mounted = True
        except CommandError as e:
            # Loop devices often fail on Docker Desktop for Mac (VirtioFS
            # doesn't support the ioctls loop needs on bind-mounted files).
            # Fall back to xorriso extraction which doesn't need loop.
            self.log("Loop mount failed, extracting ISO via xorriso...",
                     "info")
            try:
                self.executor.run(
                    f"xorriso -osirrox on -indev '{wsl_iso}' "
                    f"-extract {config.PARTIMAG_PATH} "
                    f"{self._iso_mount}{config.PARTIMAG_PATH}",
                    timeout=600,
                )
            except CommandError as e2:
                raise PipelineError("Extract",
                    f"Failed to mount ISO (loop device unavailable) "
                    f"and xorriso extraction also failed:\n{e2.output}"
                ) from e2

        self.log("ISO mounted. Looking for game partition image...", "info")

        # Find the sda3 partclone parts
        partimag = f"{self._iso_mount}{config.PARTIMAG_PATH}"
        part_prefix = f"{partimag}/{config.GAME_PARTITION}.ext4-ptcl-img.gz"
        try:
            parts_out = self.executor.run(
                f"ls -1 {part_prefix}.* 2>/dev/null | sort",
                timeout=10,
            )
        except CommandError:
            parts_out = ""

        parts = [p.strip() for p in parts_out.strip().split("\n") if p.strip()]
        if not parts:
            raise PipelineError("Extract",
                f"No partclone image found for {config.GAME_PARTITION} in ISO.\n"
                f"Expected files like {config.GAME_PARTITION}.ext4-ptcl-img.gz.aa")

        total_size = 0
        for p in parts:
            try:
                sz = self.executor.run(f"stat -c%s '{p}'", timeout=5).strip()
                total_size += int(sz)
            except (CommandError, ValueError):
                pass

        self.log(
            f"Found {len(parts)} part(s), {total_size / (1024**3):.1f} GB compressed. "
            "Converting to raw ext4...",
            "info",
        )

        # Native partclone.restore is the primary converter — it's what every
        # field install has actually been running (the Docker image ships it;
        # WSL gets a one-time apt install).  The bundled Python converter
        # (partclone_to_raw.py) is the fallback for environments where
        # partclone is missing and can't be installed (e.g. offline WSL).
        self._check_cancel()

        has_partclone = False
        try:
            self.executor.run("which partclone.restore", timeout=5)
            has_partclone = True
        except CommandError:
            pass

        if not has_partclone:
            self.log("Installing partclone (one-time setup)...", "info")
            try:
                self.executor.run(
                    "DEBIAN_FRONTEND=noninteractive apt-get install -y partclone 2>&1",
                    timeout=120,
                )
                has_partclone = True
                self.log("partclone installed.", "success")
            except CommandError:
                pass

        if has_partclone:
            self._extract_with_partclone(parts)
        else:
            script_path = _find_project_file("partclone_to_raw.py")
            if os.path.isfile(script_path):
                self.log(
                    "partclone unavailable, using bundled Python converter...",
                    "info")
                self._extract_with_python(parts, script_path)
            else:
                raise PipelineError("Extract",
                    "No extraction method available.\n"
                    "partclone could not be installed and the bundled\n"
                    "partclone_to_raw.py converter is missing.\n"
                    "Install partclone manually: wsl -u root -- apt install partclone")

        # Verify the output
        try:
            sz = self.executor.run(f"stat -c%s '{self._raw_img_path}'", timeout=5).strip()
            size_gb = int(sz) / (1024**3)
            self.log(f"Extraction complete: {size_gb:.1f} GB raw image.", "success")
        except CommandError as e:
            raise PipelineError("Extract",
                f"Raw image was not created: {e.output}") from e

    @staticmethod
    def _truncated_restore_message(last_pct, output=""):
        """Error text for a restore that stopped before the end."""
        msg = (
            f"partclone.restore stopped at {last_pct}% — the extracted "
            f"filesystem would be incomplete, so most game files would be "
            f"missing from the extract.\n\n"
            f"This usually means the helper Linux environment ran out of "
            f"disk space, or the .iso itself is truncated (re-download or "
            f"re-copy it from the USB stick and try again)."
        )
        if output:
            msg += f"\n\n{output}"
        return msg

    def _extract_with_partclone(self, parts):
        """Use native partclone.restore to convert compressed image to raw."""
        self.log("Using partclone.restore (native, fast)...", "info")
        # Concatenate split files and pipe through partclone
        # -C = disable size checking (needed for file output)
        # -O = overwrite output file
        cat_parts = " ".join(f"'{p}'" for p in parts)
        # pipefail: without it the pipeline's exit status is partclone's
        # alone, so a cat/gunzip that dies mid-stream just looks like EOF —
        # partclone stops early, exits 0, and we mount a filesystem that is
        # missing most of its files (seen in the field as a decrypt run that
        # walks a fraction of the assets).
        cmd = (
            f"set -o pipefail; cat {cat_parts} | gunzip -c | "
            f"partclone.restore -C -s - -O '{self._raw_img_path}' 2>&1"
        )

        last_pct = -1
        try:
            for line in self.executor.stream(cmd, timeout=config.EXTRACT_TIMEOUT):
                if self.cancelled:
                    self.executor.kill()
                    raise PipelineError("Extract", "Cancelled by user.")
                # partclone outputs progress with ANSI escapes like:
                # "Elapsed: 00:00:08, Remaining: 00:01:17, Completed:   9.33%,   3.71GB/min,"
                # Strip ANSI escape codes
                clean = re.sub(r'\x1b\[[^m]*m|\[A', '', line).strip()
                if not clean:
                    continue
                m = re.search(r'Completed:\s*(\d+\.?\d*)%', clean)
                if m:
                    pct = float(m.group(1))
                    ipct = int(pct)
                    if ipct > last_pct:
                        last_pct = ipct
                        # partclone also prints a "Remaining:" field, but it's
                        # derived from instantaneous throughput and swings as the
                        # image hits sparse vs dense regions — it never converges,
                        # so we don't surface it as an ETA.  The progress bar and
                        # the elapsed timer carry the real signal.
                        self.on_progress(ipct, 100, "Extracting filesystem…")
                        # Log every 10%
                        if ipct % 10 == 0:
                            self.log(f"  Extraction: {ipct}%", "info")
                elif any(kw in clean for kw in [
                    "File system", "Device size", "Space in use",
                    "Block size", "error", "Error", "done", "Starting"
                ]):
                    self.log(f"  {clean}", "info")
        except CommandError as e:
            # Out of space leaves a truncated-but-present image behind, so the
            # "non-empty output" forgiveness below would wave it through and
            # the corruption would only surface as a baffling mount failure.
            if _ENOSPC in (e.output or ""):
                raise PipelineError("Extract", _with_disk_full_hint(
                    f"partclone.restore ran out of space: {e.output}")) from e
            # partclone may exit non-zero but still produce valid output —
            # but only once it has actually restored the whole image.  A
            # failure part-way through leaves a mountable-but-gutted
            # filesystem, which is far worse than a loud error.
            if 0 <= last_pct < _RESTORE_COMPLETE_PCT:
                raise PipelineError("Extract", _with_disk_full_hint(
                    self._truncated_restore_message(last_pct, e.output))) from e
            try:
                self.executor.run(f"test -s '{self._raw_img_path}'", timeout=5)
            except CommandError:
                raise PipelineError("Extract",
                    f"partclone.restore failed: {e.output}") from e
        else:
            # Clean exit is not proof of a complete restore: with a truncated
            # or unreadable source, partclone sees EOF and stops happily.
            if 0 <= last_pct < _RESTORE_COMPLETE_PCT:
                raise PipelineError("Extract",
                    self._truncated_restore_message(last_pct))

        # partclone.restore -C creates a truncated image containing only
        # used blocks. The ext4 driver requires the image to be at least
        # block_count * block_size bytes. Read the expected size from the
        # ext4 superblock and extend the file if needed.
        try:
            sb_info = self.executor.run(
                f"dumpe2fs -h '{self._raw_img_path}' 2>/dev/null | "
                f"grep -E '^Block (count|size):'",
                timeout=15,
            ).strip()
            sb_blocks = 0
            sb_bsize = 0
            for sb_line in sb_info.split("\n"):
                if "Block count:" in sb_line:
                    sb_blocks = int(sb_line.split(":")[1].strip())
                elif "Block size:" in sb_line:
                    sb_bsize = int(sb_line.split(":")[1].strip())
            if sb_blocks and sb_bsize:
                expected_size = sb_blocks * sb_bsize
                actual = int(self.executor.run(
                    f"stat -c%s '{self._raw_img_path}'", timeout=5).strip())
                if actual < expected_size:
                    self.log(
                        f"Extending image to full filesystem size "
                        f"({expected_size / (1024**3):.1f} GB)...", "info")
                    self.executor.run(
                        f"truncate -s {expected_size} '{self._raw_img_path}'",
                        timeout=30,
                    )
        except (CommandError, ValueError):
            pass  # If we can't extend, mount will fail with a clear error

    def _extract_with_python(self, parts, script_path=None):
        """Use the bundled Python partclone converter (partclone_to_raw.py)."""
        self.log("Using Python partclone converter...", "info")
        # Docker: use the pre-staged copy in /tmp (avoids /Applications mount)
        from .executor import DockerExecutor
        if isinstance(self.executor, DockerExecutor) and hasattr(self, '_docker_partclone_path'):
            wsl_script = self._docker_partclone_path
        else:
            if script_path is None:
                script_path = _find_project_file("partclone_to_raw.py")
            wsl_script = self.executor.to_exec_path(script_path)
        parts_str = " ".join(f"'{p}'" for p in parts)
        cmd = f"PYTHONUNBUFFERED=1 python3 '{wsl_script}' '{self._raw_img_path}' {parts_str} 2>&1"

        try:
            for line in self.executor.stream(cmd, timeout=config.EXTRACT_TIMEOUT):
                if self.cancelled:
                    self.executor.kill()
                    raise PipelineError("Extract", "Cancelled by user.")
                self.log(f"  {line.strip()}", "info")
                if "Progress:" in line:
                    m = re.search(r'(\d+\.?\d*)%', line)
                    if m:
                        pct = float(m.group(1))
                        self.on_progress(int(pct), 100, "Extracting filesystem...")
        except CommandError as e:
            raise PipelineError("Extract", _with_disk_full_hint(
                f"Python extraction failed: {e.output}")) from e

    # --- Phase 1: Mount ---

    def _phase_mount(self):
        self.log("Mounting ext4 image...", "info")
        # Use the extracted raw image if we came from an ISO, otherwise use the input directly
        if self._raw_img_path:
            wsl_img = self._raw_img_path
        else:
            wsl_img = self.executor.to_exec_path(self.image_path)

        # Clean up stale mounts and loop devices from previous runs
        self._cleanup_stale_mounts(wsl_img)

        tag = uuid.uuid4().hex[:8]
        self.mount_point = f"{config.MOUNT_PREFIX}{tag}"

        try:
            self.executor.run(f"mkdir -p {self.mount_point}", timeout=10)
            self.executor.run(
                f"mount -o loop '{wsl_img}' {self.mount_point}",
                timeout=config.MOUNT_TIMEOUT,
            )
            self.log(f"Mounted at {self.mount_point}", "success")
        except CommandError as e:
            # Out of space is not a corrupt-image problem — re-extracting into
            # the same full disk just burns minutes and fails the same way.
            if _ENOSPC in (e.output or ""):
                raise PipelineError("Mount", _with_disk_full_hint(
                    f"Failed to mount image: {e.output}")) from e
            # If this was a cached image, it may be corrupt — delete and re-extract
            if self._raw_img_path and self._is_iso():
                self.log(
                    "Mount failed. Deleting image and re-extracting...",
                    "info",
                )
                try:
                    self.executor.run(f"rmdir '{self.mount_point}' 2>/dev/null; true", timeout=5)
                except CommandError:
                    pass
                try:
                    self.executor.run(f"rm -f '{self._raw_img_path}'", timeout=10)
                except CommandError:
                    pass

                # Re-run extraction from scratch
                self.on_phase(0)
                self._raw_img_path = self._raw_img_cache_path()
                self._phase_extract()
                self._check_cancel()

                # Retry mount with fresh image
                self.on_phase(1)
                wsl_img = self._raw_img_path
                self._cleanup_stale_mounts(wsl_img)
                tag = uuid.uuid4().hex[:8]
                self.mount_point = f"{config.MOUNT_PREFIX}{tag}"
                try:
                    self.executor.run(f"mkdir -p {self.mount_point}", timeout=10)
                    self.executor.run(
                        f"mount -o loop '{wsl_img}' {self.mount_point}",
                        timeout=config.MOUNT_TIMEOUT,
                    )
                    self.log(f"Mounted at {self.mount_point}", "success")
                except CommandError as e2:
                    raise PipelineError("Mount", _with_disk_full_hint(
                        f"Failed to mount freshly extracted image: {e2.output}")) from e2
            else:
                raise PipelineError("Mount", _with_disk_full_hint(
                    f"Failed to mount image: {e.output}")) from e

    def _cleanup_stale_mounts(self, wsl_img):
        """Clean up stale mount points and loop devices from previous runs."""
        # Find and unmount all jjp mount points (reverse order: submounts first)
        try:
            self.executor.run(
                f"findmnt -rn -o TARGET | grep '{config.MOUNT_PREFIX}' | sort -r | "
                f"xargs -r -I{{}} umount -lf '{{}}' 2>/dev/null; true",
                timeout=30,
            )
            # Remove empty mount directories
            self.executor.run(
                f"find /mnt -maxdepth 1 -name 'jjp_*' -type d -empty -delete 2>/dev/null; true",
                timeout=10,
            )
            self.log("Cleaned up stale mounts.", "info")
        except CommandError:
            pass

        # Detach any stale loop devices for this image
        try:
            loops = self.executor.run(
                f"losetup -j '{wsl_img}' 2>/dev/null",
                timeout=10,
            ).strip()
            for line in loops.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Format: "/dev/loop3: [64769]:1234 (/tmp/jjp_raw_foo.img)"
                loop_dev = line.split(":")[0]
                self.log(f"Detaching stale loop device: {loop_dev}", "info")
                try:
                    self.executor.run(f"losetup -d '{loop_dev}' 2>/dev/null; true", timeout=5)
                except CommandError:
                    pass
        except CommandError:
            pass

    # --- Phase 2: Detect game + chroot ---

    def _phase_chroot(self):
        self.log("Scanning for game...", "info")

        try:
            result = self.executor.run(
                f"ls -1 {self.mount_point}{config.GAME_BASE_PATH}/",
                timeout=15,
            )
        except CommandError as e:
            raise PipelineError("Chroot",
                f"No JJP game found at {config.GAME_BASE_PATH}/. "
                "Is this a valid JJP filesystem image?") from e

        # Find game directories (filter out plain files)
        candidates = []
        for name in result.strip().split("\n"):
            name = name.strip()
            if not name:
                continue
            game_path = f"{self.mount_point}{config.GAME_BASE_PATH}/{name}/game"
            try:
                self.executor.run(f"test -f '{game_path}'", timeout=5)
                candidates.append(name)
            except CommandError:
                pass

        if not candidates:
            raise PipelineError("Chroot",
                "No game binary found. Expected <game>/game in "
                f"{config.GAME_BASE_PATH}/")

        self.game_name = candidates[0]
        display = config.KNOWN_GAMES.get(self.game_name, self.game_name)
        self.log(f"Detected game: {display} ({self.game_name})", "success")

        # Set up bind mounts for chroot
        self.log("Setting up chroot environment...", "info")
        all_mounts = list(config.BIND_MOUNTS) + ["/dev/bus/usb"]
        total_mounts = len(all_mounts)
        for idx, target in enumerate(all_mounts):
            self.on_progress(idx, total_mounts, f"Mounting {target}")
            chroot_target = f"{self.mount_point}{target}"
            try:
                self.executor.run(f"mkdir -p '{chroot_target}'", timeout=5)
                self.executor.run(
                    f"mountpoint -q '{chroot_target}' 2>/dev/null || "
                    f"mount --bind {target} '{chroot_target}'",
                    timeout=10,
                )
                self._bind_mounted.append(target)
            except CommandError as e:
                self.log(f"Warning: bind mount {target} failed: {e.output}", "error")

        self.on_progress(total_mounts, total_mounts, "Done")

        # Ensure /tmp exists and is writable
        self.executor.run(f"mkdir -p {self.mount_point}/tmp && "
                     f"chmod 1777 {self.mount_point}/tmp", timeout=5)

        self.log("Chroot environment ready.", "success")

    # --- Phase 3: Dongle ---

    def _bind_dongle(self, usbipd):
        """Ensure the HASP dongle is bound (shared) in usbipd.

        Binding is required before attaching to WSL and must be done as
        administrator. The binding persists across reboots but is lost if
        the dongle moves to a different USB port.
        """
        # Check if already bound by looking at usbipd list output
        rc, stdout, _ = self.executor.run_win([usbipd, "list"], timeout=15)
        if rc != 0:
            return

        # Find the line with our dongle and check if it's already shared/bound
        # States: "Not shared", "Shared", "Attached" — must exclude "Not shared"
        for line in stdout.split("\n"):
            if config.HASP_VID_PID in line:
                lower = line.lower()
                if "not shared" in lower:
                    break  # Needs binding
                if "shared" in lower or "attached" in lower:
                    self.log("Dongle already bound (shared).", "info")
                    return
                break

        # Not bound — bind with admin elevation
        self.log("Binding dongle for USB passthrough (requires admin)...", "info")
        rc, _, stderr = self.executor.run_win(
            ["powershell", "-Command",
             f"Start-Process '{usbipd}' -ArgumentList "
             f"'bind --hardware-id {config.HASP_VID_PID}' "
             f"-Verb RunAs -Wait"],
            timeout=30,
        )
        if rc != 0 and stderr.strip():
            self.log(f"Warning: usbipd bind returned: {stderr.strip()}", "info")
        else:
            self.log("Dongle bound successfully.", "success")

    def _phase_dongle(self):
        self.log("Checking for HASP dongle...", "info")
        usbipd = find_usbipd()

        # Check dongle on Windows side via usbipd
        rc, stdout, stderr = self.executor.run_win(
            [usbipd, "list"], timeout=15
        )
        if rc != 0:
            raise PipelineError("Dongle",
                "usbipd-win not found or failed. "
                "Install from: https://github.com/dorssel/usbipd-win")

        if config.HASP_VID_PID not in stdout:
            raise PipelineError("Dongle",
                f"Sentinel HASP dongle ({config.HASP_VID_PID}) not detected.\n"
                "Please plug in the correct dongle and try again.")

        self.log("Dongle detected on Windows. Attaching to WSL...", "info")

        # Ensure dongle is bound (shared) — required when dongle moves to a new port
        self._bind_dongle(usbipd)

        # Detach first to ensure clean state (previous run may have left it attached)
        self.executor.run_win(
            [usbipd, "detach", "--hardware-id", config.HASP_VID_PID],
            timeout=10,
        )
        time.sleep(1)

        # Attach to WSL
        rc, stdout, stderr = self.executor.run_win(
            [usbipd, "attach", "--wsl", "--hardware-id", config.HASP_VID_PID],
            timeout=30,
        )
        if rc != 0:
            # May need admin elevation
            if "access" in stderr.lower() or "administrator" in stderr.lower():
                self.log("Requesting admin elevation for USB passthrough...", "info")
                rc2, _, stderr2 = self.executor.run_win(
                    ["powershell", "-Command",
                     f"Start-Process '{usbipd}' -ArgumentList "
                     f"'attach --wsl --hardware-id {config.HASP_VID_PID}' "
                     f"-Verb RunAs -Wait"],
                    timeout=30,
                )
                if rc2 != 0:
                    raise PipelineError("Dongle",
                        f"Failed to attach dongle to WSL (admin): {stderr2}")
            elif "already" in stderr.lower():
                self.log("Dongle already attached to WSL.", "info")
            elif "not shared" in stderr.lower() or "bind" in stderr.lower():
                # Binding may have failed silently — retry bind + attach
                self.log("Device not shared, retrying bind...", "info")
                self._bind_dongle(usbipd)
                time.sleep(1)
                rc2, _, stderr2 = self.executor.run_win(
                    [usbipd, "attach", "--wsl", "--hardware-id", config.HASP_VID_PID],
                    timeout=30,
                )
                if rc2 != 0:
                    raise PipelineError("Dongle",
                        f"Failed to attach dongle to WSL after bind: {stderr2}")
            else:
                raise PipelineError("Dongle",
                    f"Failed to attach dongle to WSL: {stderr}")

        # Wait for USB device to appear in WSL (usbipd attach is async)
        self.log("Waiting for dongle to appear in WSL...", "info")
        # Total wait steps: USB settle + 3s interface settle + daemon ready
        total_wait = config.USB_SETTLE_TIMEOUT + 3 + config.DAEMON_READY_TIMEOUT
        step = 0

        dongle_visible = False
        for i in range(config.USB_SETTLE_TIMEOUT):
            self.on_progress(step, total_wait, "Waiting for USB device...")
            time.sleep(1)
            step += 1
            try:
                self.executor.run(
                    f"lsusb 2>/dev/null | grep -q '{config.HASP_VID_PID}'",
                    timeout=5,
                )
                dongle_visible = True
                self.log(f"Dongle visible in WSL (after {i + 1}s).", "success")
                step = config.USB_SETTLE_TIMEOUT  # skip remaining USB wait
                break
            except CommandError:
                if i < config.USB_SETTLE_TIMEOUT - 1:
                    self.log(f"  Not visible yet ({i + 1}s)...", "info")

        if not dongle_visible:
            self.log("Warning: Dongle not visible in lsusb after waiting. "
                     "Will try starting daemon anyway...", "error")

        # Extra wait for HASP USB interface to fully initialize
        self.log("Letting USB interface settle...", "info")
        for i in range(3):
            self.on_progress(step, total_wait, "USB interface settling...")
            time.sleep(1)
            step += 1

        # Now start the HASP daemon (after USB device is confirmed visible)
        self._start_hasp_daemon(step, total_wait)

    def _reattach_dongle(self):
        """Detach and re-attach the HASP dongle to WSL, then restart the daemon.

        Used during retries when the dongle session fails. The USB device
        may have lost its connection to WSL, so we do the full cycle:
        bind (if needed) → detach → attach → wait for lsusb → restart daemon.
        """
        self.log("Re-attaching dongle to WSL...", "info")
        usbipd = find_usbipd()

        # Ensure bound (may have moved to a different port)
        self._bind_dongle(usbipd)

        # Detach
        self.executor.run_win(
            [usbipd, "detach", "--hardware-id", config.HASP_VID_PID],
            timeout=10,
        )
        time.sleep(2)

        # Attach
        rc, stdout, stderr = self.executor.run_win(
            [usbipd, "attach", "--wsl", "--hardware-id", config.HASP_VID_PID],
            timeout=30,
        )
        if rc != 0 and "already" not in stderr.lower():
            self.log(f"Warning: usbipd attach returned: {stderr}", "error")

        # Wait for device to appear in WSL
        for i in range(config.USB_SETTLE_TIMEOUT):
            time.sleep(1)
            try:
                self.executor.run(
                    f"lsusb 2>/dev/null | grep -q '{config.HASP_VID_PID}'",
                    timeout=5,
                )
                self.log(f"Dongle visible in WSL (after {i + 1}s).", "success")
                break
            except CommandError:
                pass
        else:
            self.log("Warning: Dongle not visible in lsusb after re-attach.", "error")

        # Extra settle time
        time.sleep(2)

        # Restart daemon
        self._start_hasp_daemon()

    def _start_hasp_daemon(self, progress_step=0, progress_total=0):
        """Kill any existing HASP daemon and start a fresh one.

        Runs the daemon from the WSL host (not inside the chroot) so it has
        direct access to USB devices and udev. The game in the chroot
        connects to the daemon via localhost:1947 (shared network namespace).
        """
        self.log("Starting HASP daemon...", "info")
        mp = self.mount_point
        step = progress_step

        # Kill any existing daemon first (both host and chroot)
        try:
            self.executor.run("killall hasplmd_x86_64 2>/dev/null; true", timeout=10)
            time.sleep(1)
        except CommandError:
            pass

        # Run daemon from WSL host with LD_LIBRARY_PATH pointing into the
        # mounted image's libraries so dynamic dependencies resolve.
        daemon_bin = f"{mp}{config.HASP_DAEMON_PATH}"
        lib_paths = f"{mp}/usr/lib/x86_64-linux-gnu:{mp}/usr/lib:{mp}/lib/x86_64-linux-gnu:{mp}/lib"
        try:
            self.executor.run(
                f"LD_LIBRARY_PATH={lib_paths} {daemon_bin} -s 2>&1",
                timeout=15,
            )
        except CommandError:
            # Fallback: try inside chroot (may work if host approach fails
            # due to glibc version mismatch)
            self.log("Host daemon start failed, trying inside chroot...", "info")
            try:
                self.executor.run(
                    f"chroot {mp} {config.HASP_DAEMON_PATH} -s 2>&1",
                    timeout=15,
                )
            except CommandError as e:
                raise PipelineError("Dongle",
                    f"Failed to start HASP daemon: {e.output}") from e

        # Wait for daemon to initialize and start listening on port 1947
        self.log("Waiting for HASP daemon to initialize...", "info")
        daemon_ready = False
        for attempt in range(config.DAEMON_READY_TIMEOUT):
            if progress_total > 0:
                self.on_progress(step, progress_total, "Waiting for daemon...")
            time.sleep(1)
            step += 1
            # Check daemon is still running
            try:
                self.executor.run("pgrep -f hasplmd", timeout=5)
            except CommandError:
                raise PipelineError("Dongle",
                    "HASP daemon died unexpectedly. "
                    "Check that the dongle is properly connected.")
            # Check if daemon is listening on port 1947
            try:
                self.executor.run(
                    "bash -c 'echo > /dev/tcp/127.0.0.1/1947' 2>/dev/null",
                    timeout=3,
                )
                daemon_ready = True
                break
            except CommandError:
                if attempt < config.DAEMON_READY_TIMEOUT - 1:
                    self.log(f"  Daemon not ready yet ({attempt + 1}s)...", "info")

        if daemon_ready:
            if progress_total > 0:
                self.on_progress(progress_total, progress_total, "Dongle ready")
            self.log("HASP daemon running and accepting connections.", "success")
        else:
            self.log("HASP daemon running but port 1947 not detected. "
                     "Continuing anyway...", "info")

    # --- Phase 4: Compile ---

    def _phase_compile(self):
        self.log("Compiling decryptor...", "info")
        mp = self.mount_point

        # Write C source to a temp file and copy into chroot.
        # (base64 via echo exceeds Windows command-line length limit for large sources)
        import tempfile, os
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.c', delete=False,
                dir=self.executor.host_tmp_dir(),
            ) as tf:
                # Upstream (pinned verbatim) shim + the unified-app
                # engine-agnostic hooks that make it fire on non-Allegro
                # titles (e.g. Sonic).  See DECRYPT_ENGINE_HOOKS_C.
                tf.write(DECRYPT_C_SOURCE + DECRYPT_ENGINE_HOOKS_C)
                tmp_win = tf.name
            wsl_tmp = self.executor.to_exec_path(tmp_win)
            self.executor.run(f"cp '{wsl_tmp}' {mp}/tmp/jjp_decrypt.c", timeout=15)
            os.unlink(tmp_win)
        except (CommandError, OSError) as e:
            raise PipelineError("Compile",
                f"Failed to write C source: {e}") from e

        # Compile using WSL host gcc, but link against chroot's libc to
        # avoid glibc version mismatch (host glibc may be newer than chroot's)
        chroot_lib = f"{mp}/lib/x86_64-linux-gnu"
        try:
            self.executor.run(
                f"gcc -c -fPIC -std=gnu11 -D_FORTIFY_SOURCE=0 -fno-stack-protector "
                f"-o {mp}/tmp/jjp_decrypt.o {mp}/tmp/jjp_decrypt.c 2>&1",
                timeout=config.COMPILE_TIMEOUT,
            )
            self.executor.run(
                f"LIBS='{chroot_lib}/libc.so.6'; "
                f"[ -f '{chroot_lib}/libdl.so.2' ] && LIBS=\"$LIBS {chroot_lib}/libdl.so.2\"; "
                f"gcc -shared -nostdlib "
                f"-o {mp}/tmp/jjp_decrypt.so {mp}/tmp/jjp_decrypt.o $LIBS -lgcc 2>&1",
                timeout=config.COMPILE_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Compile",
                f"gcc compilation failed: {e.output}\n"
                "Ensure gcc is installed in WSL: wsl -u root -- apt install gcc") from e

        self.log("Decryptor compiled.", "success")

        # Compile stub libraries using WSL host gcc
        self.log("Building stub libraries...", "info")
        stubs_dir = f"{mp}/tmp/stubs"
        # Clean stubs directory first to remove stale stubs from previous runs
        self.executor.run(f"rm -rf {stubs_dir}", timeout=5)
        self.executor.run(f"mkdir -p {stubs_dir}", timeout=5)

        # Write stub.c
        stub_b64 = base64.b64encode(STUB_C_SOURCE.encode()).decode()
        self.executor.run(
            f"echo '{stub_b64}' | base64 -d > {stubs_dir}/stub.c",
            timeout=10,
        )

        # Only stub libraries that are MISSING from the chroot.
        # Real libraries (e.g. Allegro) must not be replaced by empty stubs.
        total_sonames = len(config.STUB_SONAMES)
        built = 0
        skipped = 0
        for idx, soname in enumerate(config.STUB_SONAMES):
            self.on_progress(idx, total_sonames, soname)
            # Check if this library already exists in the chroot
            try:
                self.executor.run(
                    f"chroot {mp} /bin/sh -c 'ldconfig -p 2>/dev/null | grep -q {soname} || "
                    f"test -f /usr/lib/{soname} || "
                    f"test -f /usr/lib/x86_64-linux-gnu/{soname} || "
                    f"find /usr/lib -name {soname} -quit 2>/dev/null | grep -q .'",
                    timeout=10,
                )
                skipped += 1
                continue  # Library exists in chroot, don't stub it
            except CommandError:
                pass  # Library not found, create a stub

            try:
                self.executor.run(
                    f"gcc -shared -o {stubs_dir}/{soname} "
                    f"{stubs_dir}/stub.c -Wl,-soname,{soname} -nostdlib -nodefaultlibs "
                    f"2>/dev/null || "
                    f"gcc -shared -o {stubs_dir}/{soname} "
                    f"{stubs_dir}/stub.c -Wl,-soname,{soname}",
                    timeout=15,
                )
                built += 1
            except CommandError:
                pass  # Non-critical

        self.on_progress(total_sonames, total_sonames, "Done")
        self._stubs_built = built
        self.log(
            f"Built {built} stub libraries ({skipped} already in chroot, skipped).",
            "success",
        )

        # Discover dongle/hasp/init symbols for debugging and init sequence
        game_path = f"{mp}{config.GAME_BASE_PATH}/{self.game_name}/game"
        try:
            result = self.executor.run(
                f"nm -D {game_path} 2>/dev/null | grep -iE 'dongle|hasp|crypt|init' "
                f"| head -30",
                timeout=15,
            )
            if result.strip():
                self.log(f"Game symbols (dongle/hasp/crypt/init):", "info")
                for line in result.strip().split('\n'):
                    self.log(f"  {line.strip()}", "info")
        except CommandError:
            pass

    # --- Phase 5: Decrypt ---

    def _phase_decrypt(self):
        self.log("Starting decryption...", "info")
        mp = self.mount_point
        game_bin = f"{config.GAME_BASE_PATH}/{self.game_name}/game"
        decrypt_dir = "/tmp/jjp_decrypted"

        # Only set LD_LIBRARY_PATH if we actually built stub libraries;
        # otherwise the stubs dir is empty and we don't want it on the path.
        ld_lib_path = f"LD_LIBRARY_PATH=/tmp/stubs " if getattr(self, '_stubs_built', 0) > 0 else ""
        cmd = (
            f"chroot {mp} /bin/bash -c '"
            f"export JJP_OUTPUT_DIR={decrypt_dir}; "
            f"unset DISPLAY; "
            f"LD_PRELOAD=/tmp/jjp_decrypt.so "
            f"{ld_lib_path}"
            f"{game_bin}"
            f"' 2>&1"
        )

        # Retry logic: the HASP daemon may need extra time to fully discover
        # the USB key, especially through usbipd. If the game exits with
        # "key not found", wait and retry.
        max_retries = 3
        retry_wait = 5  # seconds between retries

        for attempt in range(max_retries):
            total_files = 0
            final_ok = 0
            final_fail = 0
            final_total = 0
            sentinel_error = False
            output_lines = []

            total_re = re.compile(r'\[decrypt\] TOTAL_FILES=(\d+)')
            progress_re = re.compile(
                r'Progress:\s*(\d+)\s*\(ok=(\d+)\s+fail=(\d+)\s+skip=(\d+)\)')
            result_re = re.compile(
                r'Total:\s*(\d+)\s+OK:\s*(\d+)\s+Failed:\s*(\d+)\s+Skipped:\s*(\d+)')

            try:
                for line in self.executor.stream(cmd, timeout=config.DECRYPT_TIMEOUT):
                    if self.cancelled:
                        self.executor.kill()
                        raise PipelineError("Decrypt", "Cancelled by user.")

                    output_lines.append(line)

                    # Detect Sentinel errors (key not found, terminal services, etc.)
                    if ("key not found" in line.lower() or "H0007" in line
                            or "Terminal services" in line or "H0027" in line):
                        sentinel_error = True

                    # Log every line
                    level = "info"
                    if "[FAIL]" in line or "ERROR" in line or "FAILED" in line:
                        level = "error"
                    elif "[OK]" in line or "decrypted OK" in line:
                        level = "success"
                    self.log(line, level)

                    # Parse total files
                    m = total_re.search(line)
                    if m:
                        total_files = int(m.group(1))
                        self.on_progress(0, total_files, "Decrypting...")

                    # Parse progress
                    m = progress_re.search(line)
                    if m:
                        current = int(m.group(1))
                        ok = int(m.group(2))
                        fail = int(m.group(3))
                        skip = int(m.group(4))
                        desc = f"ok={ok} fail={fail} skip={skip}"
                        self.on_progress(current, total_files, desc)

                    # Parse final result
                    m = result_re.search(line)
                    if m:
                        final_total = int(m.group(1))
                        final_ok = int(m.group(2))
                        final_fail = int(m.group(3))

            except CommandError:
                # Exit code from syscall(SYS_exit_group, 0) may show as non-zero
                # on some systems. Check if we got BATCH COMPLETE.
                if final_total > 0:
                    pass  # Completed successfully despite non-zero exit
                elif sentinel_error:
                    pass  # Handle below in retry logic
                else:
                    combined = "\n".join(output_lines[-5:]) if output_lines else ""
                    raise PipelineError("Decrypt",
                        f"Game process failed.\nLast output:\n{combined}")

            # If sentinel error and we have retries left, re-attach dongle and retry
            if sentinel_error and attempt < max_retries - 1:
                wait = retry_wait * (attempt + 1)
                self.log(
                    f"Sentinel key not found - re-attaching dongle and retrying "
                    f"in {wait}s (attempt {attempt + 2}/{max_retries})...",
                    "info",
                )
                time.sleep(wait)
                self._reattach_dongle()
                continue

            if sentinel_error:
                raise PipelineError("Decrypt",
                    "Sentinel HASP key not found after multiple attempts.\n"
                    "Check that the correct dongle is plugged in for this game.")

            # Success path - break out of retry loop
            break

        if final_total == 0:
            raise PipelineError("Decrypt",
                "Decryption produced no output. "
                "Check that the correct dongle is connected for this game.")

        self.on_progress(final_total, final_total, "Complete")
        self.log(
            f"Decryption finished: {final_ok} OK, {final_fail} failed "
            f"out of {final_total} files.",
            "success" if final_fail == 0 else "info",
        )

    def _phase_dev_capture(self):
        """Dump the game's decrypted asset-crypto routines for the developer.

        Runs only when ``dev_capture`` is set (dongle extract).  A second, fast
        LD_PRELOAD pass over the already-decrypted game grabs 8 KB of code from
        each crypto function (see DEV_CAPTURE_C_SOURCE) and tars it into the
        output folder as ``crypto_capture_<game>.tar.gz`` — the artifact a
        developer needs to add dongle-free support for a new title.

        Wrapped so any failure is a logged warning, never a failed extract:
        the user's assets are already decrypted by the time we get here.
        """
        if not getattr(self, "dev_capture", False):
            return
        mp = self.mount_point
        game = self.game_name or "game"
        try:
            self.log("Capturing crypto sample for the developer...", "info")
            import tempfile as _tf
            import os as _os
            with _tf.NamedTemporaryFile(
                    mode="w", suffix=".c", delete=False,
                    dir=self.executor.host_tmp_dir()) as tf:
                tf.write(DEV_CAPTURE_C_SOURCE)
                tmp_win = tf.name
            wsl_tmp = self.executor.to_exec_path(tmp_win)
            self.executor.run(f"cp '{wsl_tmp}' {mp}/tmp/jjp_capture.c", timeout=15)
            _os.unlink(tmp_win)

            chroot_lib = f"{mp}/lib/x86_64-linux-gnu"
            self.executor.run(
                f"gcc -c -fPIC -std=gnu11 -D_FORTIFY_SOURCE=0 "
                f"-fno-stack-protector -o {mp}/tmp/jjp_capture.o "
                f"{mp}/tmp/jjp_capture.c 2>&1", timeout=config.COMPILE_TIMEOUT)
            self.executor.run(
                f"LIBS='{chroot_lib}/libc.so.6'; "
                f"[ -f '{chroot_lib}/libdl.so.2' ] && "
                f"LIBS=\"$LIBS {chroot_lib}/libdl.so.2\"; "
                f"gcc -shared -nostdlib -o {mp}/tmp/jjp_capture.so "
                f"{mp}/tmp/jjp_capture.o $LIBS -lgcc 2>&1",
                timeout=config.COMPILE_TIMEOUT)

            cap_dir = "/tmp/jjp_dev_capture"
            self.executor.run(
                f"rm -rf {mp}{cap_dir}; mkdir -p {mp}{cap_dir}", timeout=10)
            game_bin = f"{config.GAME_BASE_PATH}/{self.game_name}/game"
            ld_lib_path = ("LD_LIBRARY_PATH=/tmp/stubs "
                           if getattr(self, "_stubs_built", 0) > 0 else "")
            cmd = (
                f"chroot {mp} /bin/bash -c '"
                f"export JJP_DEV_CAPTURE_DIR={cap_dir}; unset DISPLAY; "
                f"LD_PRELOAD=/tmp/jjp_capture.so {ld_lib_path}{game_bin}' 2>&1")
            for line in self.executor.stream(cmd, timeout=120):
                if "[capture]" in line:
                    self.log(line.strip(), "info")

            # tar the capture straight into the user's output folder
            wsl_out = self.executor.to_exec_path(self.output_path)
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", game)
            arc = f"crypto_capture_{safe}.tar.gz"
            self.executor.run(
                f"if [ -n \"$(ls -A {mp}{cap_dir} 2>/dev/null)\" ]; then "
                f"cd {mp}{cap_dir} && tar czf '{wsl_out}/{arc}' .; fi",
                timeout=30)
            # confirm it landed
            try:
                self.executor.run(f"test -s '{wsl_out}/{arc}'", timeout=5)
                self.log(
                    f"Developer crypto sample saved: {arc} (in the output "
                    f"folder). If this title isn't supported dongle-free yet, "
                    f"send that file to the developer to add support for "
                    f"everyone.", "success")
            except CommandError:
                self.log("Developer capture produced no data (the game's "
                         "crypto symbols may be named differently) — the "
                         "extract itself is unaffected.", "info")
        except (CommandError, OSError) as e:
            self.log(f"Developer capture skipped ({e}) — the extract itself "
                     f"is unaffected.", "info")

    # --- Phase 6: Copy ---

    def _phase_copy(self):
        self.log("Copying decrypted files to output folder...", "info")
        mp = self.mount_point
        src = f"{mp}/tmp/jjp_decrypted"
        wsl_out = self.executor.to_exec_path(self.output_path)

        try:
            self.executor.run(f"mkdir -p '{wsl_out}'", timeout=10)
        except CommandError as e:
            raise PipelineError("Copy",
                f"Failed to create output folder: {e.output}") from e

        # Count total files for progress reporting
        try:
            total_str = self.executor.run(
                f"find {src} -type f | wc -l", timeout=30,
            ).strip()
            total_files = int(total_str)
        except (CommandError, ValueError):
            total_files = 0

        if total_files > 0:
            self.log(f"Found {total_files} files to copy.", "info")
            self.on_progress(0, total_files, "Copying files...")

        # Use rsync for per-file progress reporting
        try:
            copied = 0
            for line in self.executor.stream(
                f"rsync -a --out-format='%n' {src}/ '{wsl_out}/'",
                timeout=config.COPY_TIMEOUT,
            ):
                self._check_cancel()
                line = line.strip()
                if line and not line.endswith("/"):  # skip directory entries
                    copied += 1
                    if total_files > 0 and (copied % 50 == 0 or copied == total_files):
                        self.on_progress(copied, total_files, line)
            if total_files > 0:
                self.on_progress(total_files, total_files, "Copy complete")
        except CommandError as e:
            # Fall back to plain cp if rsync is not available
            if "not found" in str(e.output).lower() or "not found" in str(e).lower():
                self.log("rsync not available, falling back to cp...", "info")
                try:
                    self.executor.run(
                        f"cp -r {src}/* '{wsl_out}/'",
                        timeout=config.COPY_TIMEOUT,
                    )
                except CommandError as e2:
                    raise PipelineError("Copy",
                        f"Failed to copy files: {e2.output}") from e2
            else:
                raise PipelineError("Copy",
                    f"Failed to copy files: {e.output}") from e

        # Count files in output
        try:
            count = self.executor.run(
                f"find '{wsl_out}' -type f | wc -l",
                timeout=30,
            ).strip()
        except CommandError:
            count = "?"

        # Get total size
        try:
            size = self.executor.run(
                f"du -sh '{wsl_out}' | cut -f1",
                timeout=30,
            ).strip()
        except CommandError:
            size = "?"

        self.log(f"Copied {count} files ({size}) to output folder.", "success")

        # Generate checksums for future modification comparison
        self._generate_checksums(wsl_out)

        # Move the raw image to the output folder so the mod pipeline can
        # mount it directly from there, and /tmp stays clean.
        if self._raw_img_path:
            import os
            img_name = self._raw_img_path.rsplit("/", 1)[-1]
            dest = f"{wsl_out}/{img_name}"
            self.log("Moving game image to output folder...", "info")
            try:
                # rsync + delete is more reliable than mv across filesystems
                last_pct = -1
                for line in self.executor.stream(
                    f"rsync --info=progress2 --no-inc-recursive --remove-source-files "
                    f"'{self._raw_img_path}' '{dest}'",
                    timeout=config.COPY_TIMEOUT,
                ):
                    self._check_cancel()
                    m = re.search(r'(\d+)%', line)
                    if m:
                        pct = int(m.group(1))
                        if pct > last_pct:
                            last_pct = pct
                            self.on_progress(pct, 100, line.strip())
                self.on_progress(100, 100, "Done")
                win_path = os.path.join(self.output_path, img_name)
                self.log(f"Game image saved to: {win_path}", "success")
            except CommandError as e:
                self.log(f"Warning: Could not move image to output: {e.output}", "info")

    # --- Phase 7: Cleanup ---

    def _phase_cleanup(self):
        self.log("Cleaning up...", "info")

        if self.mount_point:
            mp = self.mount_point

            # Kill HASP daemon (may be running on host or in chroot)
            try:
                self.executor.run(
                    "killall hasplmd_x86_64 2>/dev/null; true",
                    timeout=10,
                )
            except CommandError:
                pass

            # Detach USB from WSL (non-critical)
            usbipd = find_usbipd()
            self.executor.run_win(
                [usbipd, "detach", "--hardware-id", config.HASP_VID_PID],
                timeout=10,
            )

            # Unmount bind mounts in reverse order
            for target in reversed(self._bind_mounted):
                try:
                    self.executor.run(f"umount -l '{mp}{target}' 2>/dev/null; true", timeout=10)
                except CommandError:
                    pass

            # Unmount the ext4 image
            try:
                self.executor.run(f"umount -l '{mp}' 2>/dev/null; true", timeout=30)
            except CommandError:
                pass

            # Remove mount point
            try:
                self.executor.run(f"rmdir '{mp}' 2>/dev/null; true", timeout=5)
            except CommandError:
                pass

        # Clean up ISO mount / extraction directory
        if self._iso_mount:
            try:
                if getattr(self, '_iso_mounted', False):
                    self.executor.run(f"umount -l '{self._iso_mount}' 2>/dev/null; true", timeout=15)
                self.executor.run(f"rm -rf '{self._iso_mount}' 2>/dev/null; true", timeout=15)
            except CommandError:
                pass

        # Clean up any leftover raw image in temp dirs (it was moved to output folder)
        if self._raw_img_path and (self._raw_img_path.startswith("/tmp/") or
                                   self._raw_img_path.startswith("/var/tmp/")):
            try:
                self.executor.run(f"rm -f '{self._raw_img_path}' 2>/dev/null; true", timeout=10)
            except CommandError:
                pass

        self.log("Cleanup complete.", "success")

    # ---- debugfs helpers (shared by all pipelines) ----

    @staticmethod
    def _parse_debugfs_ls_line(line):
        """Parse one ``debugfs ls -p`` line into ``(inode, mode, name)``.

        ``debugfs 1.47.4`` (homebrew e2fsprogs on macOS) emits TWO
        different line shapes depending on the entry type:

        * **Directory**: ``/<inode>/<mode>/<uid>/<gid>/<name>//``
          — name carries debugfs's own trailing-slash dir marker,
          and the format string adds its terminator, so dir lines
          end in a double slash.  5 non-empty fields after split.
        * **File**: ``/<inode>/<mode>/<uid>/<gid>/<name>/<size>/``
          — a size column (in bytes) follows the name and there is
          no dir-marker, so file lines have **6** non-empty fields.

        The v0.7.9 fix correctly handled the dir double-slash case
        but assumed the *last* non-empty field was always the name.
        For files that picked the size (e.g. ``5462744``) instead
        of ``Mystery.webm``, so the scan added 4168 paths shaped
        like ``.../Mystery/5462744`` — none of which existed when
        the dump phase tried to read them, leaving the user staring
        at a stuck progress bar during filler-size detection.

        Name is always at fixed position **fields[4]** (the 5th
        non-empty field, immediately after inode/mode/uid/gid),
        regardless of whether a size column follows.

        Returns ``None`` for:
          * blank / non-``/``-leading lines (banners, prompts)
          * debugfs error lines like
            ``/some/path//: File not found by ext2_lookup`` —
            these start with ``/`` but the inode field is not
            numeric, which is how we discriminate
          * ``.`` and ``..`` entries (callers never want them)
        """
        if not line or not line.startswith("/"):
            return None
        parts = line.split("/")
        # Drop empty leading slot (always '') and any trailing empty
        # slots ('' for file lines, '', '' for dir lines).
        fields = [p for p in parts if p != ""]
        if len(fields) < 5:
            return None
        inode, mode = fields[0], fields[1]
        if not inode.isdigit() or not mode.isdigit():
            # Error line ("...: File not found by ext2_lookup") or
            # any non-listing output we should not classify.
            return None
        # Name is at fixed position [4] (after inode/mode/uid/gid).
        # NOT fields[-1] — for file lines a size column follows the
        # name and would otherwise be returned as the filename.
        name = fields[4]
        if name in (".", ".."):
            return None
        return inode, mode, name

    def _debugfs_run(self, command, writable=False, timeout=120):
        """Run a single debugfs command against the raw ext4 image.

        Args:
            command: debugfs command (e.g. 'ls /jjpe/gen1')
            writable: open image read-write (-w flag)
            timeout: seconds
        Returns:
            stdout string
        """
        native = getattr(self, '_native_debugfs_path', None)
        if native:
            # Native mode: run debugfs on host directly against raw device
            if getattr(self, '_use_sudo', False):
                return self._debugfs_run_elevated(
                    command, writable=writable, timeout=timeout)
            args = [native]
            if writable:
                args.append("-w")
            args.extend(["-R", command, self._wsl_img])
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=timeout)
            except subprocess.TimeoutExpired as e:
                raise CommandError(
                    f"debugfs -R '{command}'", -1,
                    f"Timed out after {timeout}s") from e
            output = (result.stdout or "") + (result.stderr or "")
            if result.returncode != 0:
                raise CommandError(
                    f"debugfs -R '{command}'", result.returncode, output)
            return output

        w = "-w " if writable else ""
        escaped = command.replace("'", "'\\''")
        return self.executor.run(
            f"debugfs {w}-R '{escaped}' '{self._wsl_img}' 2>&1",
            timeout=timeout,
        )

    def _run_shell_elevated(self, shell_cmd, timeout=120, label=None):
        """Run an arbitrary shell command as root with the cached
        admin password (single-prompt UX).

        Factored out of :meth:`_debugfs_run_elevated` so the cleanup
        ``e2fsck`` calls can reuse the cached credential instead of
        popping fresh ``with administrator privileges`` dialogs (one
        per A/B partition) at the end of every Direct-SSD run.

        Returns the combined stdout+stderr text on success.  Raises
        :class:`CommandError` for non-auth failures.  On bad-password
        rejection (-60007), clears the cache, re-prompts once, then
        raises :class:`PipelineError` if the second try also fails.
        """
        import getpass
        user = getpass.getuser()
        as_shell = shell_cmd.replace('\\', '\\\\').replace('"', '\\"')
        user_escaped = user.replace('\\', '\\\\').replace('"', '\\"')
        what = label or shell_cmd[:60]

        for attempt in (0, 1):
            if not getattr(self, '_cached_admin_password', None):
                self._cached_admin_password = (
                    self._prompt_for_admin_password())
            pw_escaped = (self._cached_admin_password
                          .replace('\\', '\\\\').replace('"', '\\"'))
            try:
                result = subprocess.run(
                    ["osascript", "-e",
                     f'do shell script "{as_shell}" '
                     f'user name "{user_escaped}" '
                     f'password "{pw_escaped}" '
                     f'with administrator privileges'],
                    capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=timeout)
            except subprocess.TimeoutExpired as e:
                raise CommandError(
                    what, -1, f"Timed out after {timeout}s") from e
            output = (result.stdout or "") + (result.stderr or "")
            if result.returncode != 0 and "-60007" in output:
                self._cached_admin_password = None
                if attempt == 0:
                    self.log(
                        "Admin password rejected — try again.", "info")
                    continue
                raise PipelineError(
                    "Mount",
                    "Admin password failed twice. Cancelling. "
                    "Re-run Extract / Apply to try again.")
            if result.returncode != 0:
                raise CommandError(what, result.returncode, output)
            return output
        # Unreachable — loop always either returns or raises.
        return ""

    def _debugfs_run_elevated(self, command, writable=False, timeout=120):
        """Run debugfs as root with a CACHED admin password.

        macOS's ``with administrator privileges`` clause re-prompts on
        every separate osascript invocation, because the OS authorization
        cache is keyed by the calling process and ``subprocess.run`` makes
        a fresh ``osascript`` process per call.  Result on a Direct-SSD
        extract: a password dialog *per debugfs command* — dozens of
        them across a single run.  The docstring of the prior version
        claimed "5-minute OS cache, only first call prompts" but
        empirically that's only true if osascript is the long-running
        parent, which it isn't here.

        Fix: prompt the user ONCE via :meth:`_prompt_for_admin_password`,
        cache the answer on ``self._cached_admin_password``, and pass it
        explicitly to every subsequent osascript call via
        ``user name … password …`` — that clause bypasses the system
        prompt entirely because we've already supplied the credential.
        On rejection (AppleScript error -60007) we clear the cache and
        re-prompt once, so a fat-fingered first attempt doesn't abort
        the whole run.
        """
        native = self._native_debugfs_path
        w = "-w " if writable else ""
        escaped_cmd = command.replace("'", "'\\''")
        shell_cmd = (
            f"'{native}' {w}-R '{escaped_cmd}' '{self._wsl_img}' 2>&1"
        )
        return self._run_shell_elevated(
            shell_cmd, timeout=timeout,
            label=f"debugfs -R '{command}'")

    def _edata_is_populated(self, edata_dir, max_depth=3, _depth=0):
        """Quick "is the edata dir non-empty?" check via debugfs.

        JJP A/B firmware slots sometimes have ``/jjpe/gen1/<game>/
        edata`` present on the inactive slot with the FULL directory
        tree pre-created (``graphics/``, ``sound/``, etc.) but every
        leaf empty.  Looking only at the top level isn't enough —
        ``graphics/`` is a real directory entry on both the active
        and inactive slots, so a "first non-dot entry wins" heuristic
        false-positives on the empty slot and we end up scanning the
        wrong partition (the GnR drive: partition 3 had the empty
        tree, partition 5 had the live data).

        Walk recursively (bounded depth to keep this cheap — ~10
        debugfs calls on a fully-populated tree before we hit the
        first real file) and return True only when we find an actual
        *file* entry, not just a directory entry.  Returns False on
        any debugfs error — better to swap and try the partner than
        block on a transient failure.

        Verbose by design: every call logs the raw debugfs output
        and the per-entry classification.  When something off-spec
        (a debugfs version with a different ``ls -p`` format, an
        edge-case ext4 layout, a permission-denied that returns
        zero bytes instead of an error) makes this misclassify, the
        log shows exactly which line broke.  ``_depth`` is for
        readable indentation in the log only.
        """
        indent = "    " * _depth
        self.log(
            f"{indent}[edata-probe] listing {edata_dir} "
            f"(depth {_depth}/{max_depth + _depth})",
            "info")
        try:
            # Quote the path — JJP asset trees have directory
            # names with spaces (e.g. "Pyro Action Button") that
            # otherwise tokenize and make debugfs print its
            # ``Usage: ls ...`` banner and return EMPTY.
            ls_out = self._debugfs_run(
                f'ls -p "{edata_dir}"', timeout=10)
        except CommandError as e:
            self.log(
                f"{indent}[edata-probe] debugfs ls failed: "
                f"{getattr(e, 'output', e) or e}",
                "info")
            return False
        # Show the raw output so we can see exactly what debugfs
        # returned — including the banner line and any non-/-leading
        # lines we skip.  Trim aggressively so a 100k-entry dir
        # listing on a populated slot doesn't flood the log.
        preview = ls_out if len(ls_out) <= 800 else ls_out[:800] + "…"
        self.log(
            f"{indent}[edata-probe] raw ls -p output "
            f"({len(ls_out)} chars):\n{preview}",
            "info")
        found_files = 0
        found_subdirs = 0
        for line in ls_out.splitlines():
            stripped = line.strip()
            parsed = self._parse_debugfs_ls_line(stripped)
            if parsed is None:
                if stripped.startswith("/"):
                    self.log(
                        f"{indent}[edata-probe]   SKIP (unparsed): "
                        f"{stripped!r}",
                        "info")
                continue
            _inode, mode, name = parsed
            if mode.startswith("04"):
                found_subdirs += 1
                if max_depth <= 0:
                    self.log(
                        f"{indent}[edata-probe]   DIR {name} "
                        f"(mode {mode}) — depth budget exhausted, "
                        f"not recursing",
                        "info")
                    continue
                self.log(
                    f"{indent}[edata-probe]   DIR {name} "
                    f"(mode {mode}) — recursing",
                    "info")
                if self._edata_is_populated(
                        f"{edata_dir}/{name}",
                        max_depth - 1, _depth=_depth + 1):
                    self.log(
                        f"{indent}[edata-probe] → POPULATED "
                        f"(found file inside {name})",
                        "info")
                    return True
                continue
            # Anything non-directory counts as a populated entry.
            found_files += 1
            self.log(
                f"{indent}[edata-probe]   FILE {name} "
                f"(mode {mode}) → POPULATED",
                "info")
            return True
        self.log(
            f"{indent}[edata-probe] {edata_dir}: "
            f"{found_subdirs} subdir(s), {found_files} file(s) "
            f"directly — returning EMPTY",
            "info")
        return False

    def _prompt_for_admin_password(self):
        """One-shot macOS admin password prompt via osascript dialog.

        Used once at the start of an elevated-mode Direct-SSD session;
        the result is cached on ``self._cached_admin_password`` and
        reused for every subsequent ``_debugfs_run_elevated`` call.

        Returns the password as a string.  Raises :class:`PipelineError`
        if the user cancels the dialog (so the calling pipeline aborts
        cleanly with an actionable message).
        """
        self.log(
            "Prompting for admin password (one-time, used only for "
            "this run — not stored)…",
            "info")
        result = subprocess.run(
            ["osascript", "-e",
             'display dialog '
             '"Pinball Asset Decryptor needs your macOS admin '
             'password to read the SSD. It is used only for this '
             'run and is not stored anywhere." '
             'default answer "" with hidden answer '
             'with title "Admin Password Required" '
             'buttons {"Cancel", "OK"} default button "OK"'],
            capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise PipelineError(
                "Mount",
                "Admin password is required to read the SSD. "
                "Cancelled.")
        # osascript prints: button returned:OK, text returned:<pw>
        # (with possible trailing fields).  We pull just the
        # text-returned value.
        m = re.search(r'text returned:(.*?)(?:, gave up:|$)',
                      result.stdout.strip())
        if not m:
            raise PipelineError(
                "Mount",
                "Could not parse password response from osascript.")
        return m.group(1)


class ModPipeline(DecryptionPipeline):
    """Runs the asset modification workflow.

    Scans the assets folder for files that differ from the original decryption
    (via checksums), then re-encrypts only the changed files into the game image.

    Reuses mount/chroot/dongle/cleanup from DecryptionPipeline.
    """

    def __init__(self, image_path, assets_folder, log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(image_path, assets_folder, log_cb, phase_cb, progress_cb, done_cb)
        self.assets_folder = assets_folder
        self.changed_files = []  # [(rel_path, abs_win_path), ...]

    def run(self):
        """Execute the mod pipeline. Call from a background thread."""
        import os
        cleanup_phase = len(config.MOD_PHASES) - 1
        try:
            # Verify paths are accessible from the executor
            for label, path in [("Game image", self.image_path),
                                ("Assets folder", self.assets_folder)]:
                ok, msg = self.executor.check_path_accessible(path)
                if not ok:
                    raise PipelineError("Scan", f"{label} path error:\n{msg}")

            # Phase 0: Scan for changes (pure Python, no WSL needed)
            self.on_phase(0)
            self._phase_scan()
            self._check_cancel()

            if not self.changed_files:
                self.on_done(True,
                    "No changes detected in the assets folder.\n"
                    "Modify files in the output folder and try again.")
                return

            self.on_phase(1)  # Extract
            self._timed("Extract", self._phase_extract)
            self._check_cancel()

            self.on_phase(2)  # Mount
            self._phase_mount()
            self._check_cancel()

            self.on_phase(3)  # Chroot
            self._phase_chroot()
            self._check_cancel()

            self.on_phase(4)  # Dongle
            self._phase_dongle()
            self._check_cancel()

            self.on_phase(5)  # Compile
            self._phase_compile_encryptor()
            self._check_cancel()

            self.on_phase(6)  # Encrypt
            self._timed("Encrypt", self._phase_encrypt)

            # Convert and Build ISO only when input is an ISO
            if self._is_iso():
                self.on_phase(7)  # Convert
                self._timed("Convert", self._phase_convert)
                self._check_cancel()

                self.on_phase(8)  # Build ISO
                self._timed("Build ISO", self._phase_build_iso)
                self._check_cancel()

            self._succeeded = True
            self.on_phase(cleanup_phase)
            self._phase_cleanup()

            if self._is_iso() and hasattr(self, '_output_iso_path'):
                win_path = self._output_iso_path
                self.log(f"Modified ISO ready at: {win_path}", "success")
                self.on_done(True,
                    f"Asset modification complete!\n"
                    f"Modified ISO at:\n{win_path}")

                self.log("", "info")
                self.log("=== Next Steps ===", "info")
                if sys.platform == "win32":
                    self.log(
                        "1. Write this ISO to a USB drive using Rufus\n"
                        "   Important: select ISO mode (NOT DD mode) when prompted\n"
                        "2. Boot the pinball machine from USB\n"
                        "3. Let Clonezilla restore the image to the machine",
                        "info",
                    )
                    self.log_link(
                        "JJP USB Update Instructions (PDF)",
                        "https://marketing.jerseyjackpinball.com/general/install-full/"
                        "JJP_USB_UPDATE_PC_instructions.pdf",
                    )
                else:
                    self.log(
                        "1. Write this ISO to a USB drive using balenaEtcher or dd\n"
                        "2. Boot the pinball machine from USB\n"
                        "3. Let Clonezilla restore the image to the machine",
                        "info",
                    )
                    if sys.platform == "darwin":
                        self.log_link(
                            "JJP USB Update Instructions for Mac (PDF)",
                            "https://marketing.jerseyjackpinball.com/general/install-full/"
                            "JJP_USB_UPDATE_MAC_instructions.pdf",
                        )
                    else:
                        self.log_link(
                            "JJP USB Update Instructions (PDF)",
                            "https://marketing.jerseyjackpinball.com/general/install-full/"
                            "JJP_USB_UPDATE_PC_instructions.pdf",
                        )
            else:
                # Fallback for non-ISO inputs: output the raw .img
                import os
                img_name = self._raw_img_path.rsplit("/", 1)[-1] if self._raw_img_path else "image"
                wsl_out = self.executor.to_exec_path(self.assets_folder)
                dest = f"{wsl_out}/{img_name}"
                win_path = os.path.join(self.assets_folder, img_name)

                if self._raw_img_path and self._raw_img_path != dest:
                    self.log("Moving modified image to output folder...", "info")
                    try:
                        last_pct = -1
                        for line in self.executor.stream(
                            f"rsync --info=progress2 --no-inc-recursive --remove-source-files "
                            f"'{self._raw_img_path}' '{dest}'",
                            timeout=config.COPY_TIMEOUT,
                        ):
                            self._check_cancel()
                            m = re.search(r'(\d+)%', line)
                            if m:
                                pct = int(m.group(1))
                                if pct > last_pct:
                                    last_pct = pct
                                    self.on_progress(pct, 100, line.strip())
                        self.on_progress(100, 100, "Done")
                    except CommandError as e:
                        self.log(f"Warning: Could not move image to output: {e.output}", "info")

                self.log(f"Modified image ready at: {win_path}", "success")
                self.on_done(True,
                    f"Asset modification complete!\n"
                    f"Modified image at:\n{win_path}")

        except PipelineError as e:
            self.log(str(e), "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup()
            self.on_done(False, str(e))
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup()
            self.on_done(False, f"Unexpected error: {e}")

    # --- Extract override ---

    def _phase_extract(self):
        """Always extract a fresh image from the original ISO for mod runs.

        Each mod run must start from a pristine image to avoid accumulated
        state from previous runs (modified files, dirty journals, etc.).
        Deletes any cached images from /tmp before extracting.
        """
        import os

        # Delete any cached image from previous runs to force fresh extraction
        cache_path = self._raw_img_cache_path()
        self.log("Clearing cached image to ensure fresh extraction...", "info")
        try:
            self.executor.run(
                f"rm -f '{cache_path}' 2>/dev/null; true", timeout=30)
        except CommandError:
            pass

        # Extract fresh from the original ISO
        super()._phase_extract()

    # --- Phase 0: Scan ---

    def _phase_scan(self):
        """Compare assets folder against saved checksums to find modified files."""
        import hashlib
        import os

        self.log("Scanning for modified files...", "info")

        checksums_file = os.path.join(self.assets_folder, '.checksums.md5')
        if not os.path.isfile(checksums_file):
            raise PipelineError("Scan",
                "No .checksums.md5 found in the assets folder.\n"
                "Run Decrypt first to generate baseline checksums.")

        # Load saved checksums
        saved = {}
        with open(checksums_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # md5sum output: "hash  ./path" or "hash *./path"
                m = re.match(r'^([a-f0-9]{32})\s+\*?(.+)$', line)
                if m:
                    filepath = m.group(2)
                    if filepath.startswith('./'):
                        filepath = filepath[2:]
                    saved[filepath] = m.group(1)

        self.log(f"Loaded {len(saved)} baseline checksums.", "info")

        # Collect files to scan
        all_files = []
        untracked_system = 0
        untracked_assets = []  # (rel_path, full_path) for non-system stragglers
        for root, _dirs, files in os.walk(self.assets_folder):
            for name in files:
                if name.startswith('.') or name == 'fl_decrypted.dat' or name.endswith('.img'):
                    continue
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, self.assets_folder).replace('\\', '/')
                if rel_path in saved:
                    all_files.append((rel_path, full_path))
                elif rel_path.startswith("system/"):
                    untracked_system += 1
                else:
                    untracked_assets.append((rel_path, full_path))

        if untracked_system > 0:
            self.log(
                f"Note: {untracked_system} system file(s) are not tracked "
                f"in .checksums.md5.\n"
                f"Re-run Decrypt with 'File System' checked to enable "
                f"system file modification tracking.",
                "info")

        total = len(all_files)
        self.on_progress(0, total, "Scanning...")
        self.log(f"Checking {total} files for changes...", "info")

        self.changed_files = []
        for i, (rel_path, full_path) in enumerate(all_files):
            if self.cancelled:
                raise PipelineError("Scan", "Cancelled by user.")

            h = hashlib.md5()
            with open(full_path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    h.update(chunk)
            new_hash = h.hexdigest()

            if saved[rel_path] != new_hash:
                self.changed_files.append((rel_path, full_path))
                self.log(f"  Modified: {rel_path}", "info")
                if hasattr(self, '_file_tree_cb'):
                    self._file_tree_cb(rel_path, "Modified")

            if (i + 1) % 500 == 0 or i + 1 == total:
                self.on_progress(i + 1, total,
                    f"{len(self.changed_files)} changed so far")

        if self.changed_files:
            self.log(
                f"Found {len(self.changed_files)} modified file(s) "
                f"out of {total} checked.",
                "success",
            )
        else:
            self.log("No modified files detected.", "info")
            # Diagnostic: when nothing is detected, surface likely
            # format-mismatch culprits — untracked files whose stem
            # matches a tracked file in the same directory but with a
            # different extension (e.g. user dropped in `song.mp3`
            # next to the original `song.ogg`).  This catches Mike's
            # exact failure mode where Windows hides extensions, the
            # "replace" looks correct visually, and the new file is
            # just a sibling rather than an overwrite.
            tracked_by_dir = {}
            for rel in saved:
                d, _, base = rel.rpartition('/')
                stem, _, _ext = base.rpartition('.')
                if stem:
                    tracked_by_dir.setdefault(d, {}).setdefault(
                        stem.lower(), base)
            collisions = []
            for rel, _ in untracked_assets:
                d, _, base = rel.rpartition('/')
                stem, _, _ext = base.rpartition('.')
                if not stem:
                    continue
                original = tracked_by_dir.get(d, {}).get(stem.lower())
                if original and original != base:
                    collisions.append((rel, f"{d}/{original}" if d else original))
            if collisions:
                lines = [
                    f"  {wrong}  (original is {orig})"
                    for wrong, orig in collisions[:10]
                ]
                more = (f"\n  …and {len(collisions) - 10} more"
                        if len(collisions) > 10 else "")
                self.log(
                    "Possible format mismatch — the following untracked "
                    "files share a name with a tracked original but use "
                    "a different extension:\n"
                    + "\n".join(lines) + more + "\n"
                    "JJP does not auto-convert formats. Replacements must "
                    "use the original file's extension (audio: .ogg, "
                    "images: PNG/JPG as originally stored).",
                    "error")
            elif untracked_assets:
                self.log(
                    f"Note: {len(untracked_assets)} untracked file(s) in "
                    "the assets folder are being ignored. Replacements "
                    "must overwrite the original file (same path, same "
                    "filename, same extension) to be picked up.",
                    "info")

    # (Backup phase removed — the original ISO serves as the backup.
    #  The raw image can be re-extracted from the ISO at any time.)

    # --- Compile ---

    def _phase_compile_encryptor(self):
        """Compile the encryptor hook (instead of decryptor)."""
        self.log("Compiling encryptor...", "info")
        mp = self.mount_point

        import tempfile, os
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.c', delete=False,
                dir=self.executor.host_tmp_dir(),
            ) as tf:
                tf.write(ENCRYPT_C_SOURCE)
                tmp_win = tf.name
            wsl_tmp = self.executor.to_exec_path(tmp_win)
            self.executor.run(f"cp '{wsl_tmp}' {mp}/tmp/jjp_encrypt.c", timeout=15)
            os.unlink(tmp_win)
        except (CommandError, OSError) as e:
            raise PipelineError("Compile",
                f"Failed to write C source: {e}") from e

        chroot_lib = f"{mp}/lib/x86_64-linux-gnu"
        try:
            self.executor.run(
                f"gcc -c -fPIC -std=gnu11 -D_FORTIFY_SOURCE=0 -fno-stack-protector "
                f"-o {mp}/tmp/jjp_encrypt.o {mp}/tmp/jjp_encrypt.c 2>&1",
                timeout=config.COMPILE_TIMEOUT,
            )
            self.executor.run(
                f"LIBS='{chroot_lib}/libc.so.6'; "
                f"[ -f '{chroot_lib}/libdl.so.2' ] && LIBS=\"$LIBS {chroot_lib}/libdl.so.2\"; "
                f"gcc -shared -nostdlib "
                f"-o {mp}/tmp/jjp_encrypt.so {mp}/tmp/jjp_encrypt.o $LIBS -lgcc 2>&1",
                timeout=config.COMPILE_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Compile",
                f"gcc compilation failed: {e.output}") from e

        self.log("Encryptor compiled.", "success")

        # Build stub libraries (same as decrypt pipeline)
        self.log("Building stub libraries...", "info")
        stubs_dir = f"{mp}/tmp/stubs"
        self.executor.run(f"rm -rf {stubs_dir}", timeout=5)
        self.executor.run(f"mkdir -p {stubs_dir}", timeout=5)

        stub_b64 = base64.b64encode(STUB_C_SOURCE.encode()).decode()
        self.executor.run(
            f"echo '{stub_b64}' | base64 -d > {stubs_dir}/stub.c",
            timeout=10,
        )

        total_sonames = len(config.STUB_SONAMES)
        built = 0
        skipped = 0
        for idx, soname in enumerate(config.STUB_SONAMES):
            self.on_progress(idx, total_sonames, soname)
            try:
                self.executor.run(
                    f"chroot {mp} /bin/sh -c 'ldconfig -p 2>/dev/null | grep -q {soname} || "
                    f"test -f /usr/lib/{soname} || "
                    f"test -f /usr/lib/x86_64-linux-gnu/{soname} || "
                    f"find /usr/lib -name {soname} -quit 2>/dev/null | grep -q .'",
                    timeout=10,
                )
                skipped += 1
                continue
            except CommandError:
                pass
            try:
                self.executor.run(
                    f"gcc -shared -o {stubs_dir}/{soname} "
                    f"{stubs_dir}/stub.c -Wl,-soname,{soname} -nostdlib -nodefaultlibs "
                    f"2>/dev/null || "
                    f"gcc -shared -o {stubs_dir}/{soname} "
                    f"{stubs_dir}/stub.c -Wl,-soname,{soname}",
                    timeout=15,
                )
                built += 1
            except CommandError:
                pass

        self.on_progress(total_sonames, total_sonames, "Done")
        self._stubs_built = built
        self.log(f"Built {built} stub libraries ({skipped} skipped).", "success")

    # --- Encrypt ---

    def _phase_encrypt(self):
        """Copy changed files into chroot, write manifest, run encryptor."""
        import os
        self.log("Preparing modified files...", "info")
        mp = self.mount_point
        repl_dir = f"{mp}/tmp/jjp_replacements"
        self.executor.run(f"rm -rf {repl_dir} && mkdir -p {repl_dir}", timeout=10)

        # Copy each changed file into the chroot
        manifest_lines = []
        for i, (rel_path, win_path) in enumerate(self.changed_files):
            self._check_cancel()
            wsl_src = self.executor.to_exec_path(win_path)
            ext = os.path.splitext(win_path)[1]
            dest_name = f"repl_{i}{ext}"
            dest_path = f"{repl_dir}/{dest_name}"
            try:
                self.executor.run(f"cp '{wsl_src}' '{dest_path}'", timeout=60)
            except CommandError as e:
                raise PipelineError("Encrypt",
                    f"Failed to copy file: {win_path}\n{e.output}") from e

            manifest_lines.append(f"{rel_path}\t/tmp/jjp_replacements/{dest_name}")
            self.log(f"  Staged: {rel_path}", "info")

        # Write manifest
        manifest_content = "\n".join(manifest_lines) + "\n"
        manifest_b64 = base64.b64encode(manifest_content.encode()).decode()
        self.executor.run(
            f"echo '{manifest_b64}' | base64 -d > {mp}/tmp/jjp_manifest.txt",
            timeout=10,
        )
        self.log(f"Manifest written with {len(self.changed_files)} entries.", "info")

        # Run the game binary with the encryptor hook
        game_bin = f"{config.GAME_BASE_PATH}/{self.game_name}/game"
        self.log("Running encryptor...", "info")
        ld_lib_path = f"LD_LIBRARY_PATH=/tmp/stubs " if getattr(self, '_stubs_built', 0) > 0 else ""

        cmd = (
            f"chroot {mp} /bin/bash -c '"
            f"export JJP_MANIFEST=/tmp/jjp_manifest.txt; "
            f"unset DISPLAY; "
            f"LD_PRELOAD=/tmp/jjp_encrypt.so "
            f"{ld_lib_path}"
            f"{game_bin}"
            f"' 2>&1"
        )

        max_retries = 3
        retry_wait = 5

        for attempt in range(max_retries):
            total_files = 0
            final_ok = 0
            final_fail = 0
            final_total = 0
            sentinel_error = False
            output_lines = []

            total_re = re.compile(r'\[encrypt\] TOTAL_FILES=(\d+)')
            progress_re = re.compile(
                r'Progress:\s*(\d+)\s*\(ok=(\d+)\s+fail=(\d+)\)')
            result_re = re.compile(
                r'Total:\s*(\d+)\s+OK:\s*(\d+)\s+Failed:\s*(\d+)')
            fl_updated_re = re.compile(r'FL_DAT_UPDATED=1')
            fl_failed_re = re.compile(r'FL_DAT_FAILED=1')
            fl_dat_updated = False
            fl_dat_failed = False

            try:
                for line in self.executor.stream(cmd, timeout=config.DECRYPT_TIMEOUT):
                    if self.cancelled:
                        self.executor.kill()
                        raise PipelineError("Encrypt", "Cancelled by user.")

                    output_lines.append(line)

                    if ("key not found" in line.lower() or "H0007" in line
                            or "Terminal services" in line or "H0027" in line):
                        sentinel_error = True

                    level = "info"
                    if "[FAIL]" in line or "VERIFY FAIL" in line or "FAILED" in line:
                        level = "error"
                    elif "[VERIFY OK]" in line or "decrypted OK" in line:
                        level = "success"
                    elif "forge:" in line and "OK" in line:
                        level = "success"
                    elif "fl.dat restored" in line:
                        level = "success"
                    elif "WARNING" in line or "WARN" in line:
                        level = "error"
                    self.log(line, level)

                    m = total_re.search(line)
                    if m:
                        total_files = int(m.group(1))
                        self.on_progress(0, total_files, "Encrypting...")

                    m = progress_re.search(line)
                    if m:
                        current = int(m.group(1))
                        ok_count = int(m.group(2))
                        fail_count = int(m.group(3))
                        desc = f"ok={ok_count} fail={fail_count}"
                        self.on_progress(current, total_files, desc)

                    m = result_re.search(line)
                    if m:
                        final_total = int(m.group(1))
                        final_ok = int(m.group(2))
                        final_fail = int(m.group(3))

                    if fl_updated_re.search(line):
                        fl_dat_updated = True
                    if fl_failed_re.search(line):
                        fl_dat_failed = True

            except CommandError:
                if final_total > 0:
                    pass
                elif sentinel_error:
                    pass
                else:
                    combined = "\n".join(output_lines[-5:]) if output_lines else ""
                    raise PipelineError("Encrypt",
                        f"Encryptor process failed.\nLast output:\n{combined}")

            if sentinel_error and attempt < max_retries - 1:
                wait = retry_wait * (attempt + 1)
                self.log(
                    f"Sentinel key not found - re-attaching dongle and retrying "
                    f"in {wait}s (attempt {attempt + 2}/{max_retries})...",
                    "info",
                )
                time.sleep(wait)
                self._reattach_dongle()
                continue

            if sentinel_error:
                raise PipelineError("Encrypt",
                    "Sentinel HASP key not found after multiple attempts.")

            break

        if final_total == 0:
            raise PipelineError("Encrypt",
                "Encryptor produced no output. Check dongle and manifest.")

        self.on_progress(final_total, final_total, "Complete")
        summary = f"{final_ok}/{final_total} files replaced and verified"
        if final_fail > 0:
            summary += f" ({final_fail} FAILED)"
            self.log(summary, "error")
        else:
            summary += " successfully"
            self.log(summary, "success")

        # CRC forgery mode: fl.dat is restored unmodified
        self.log("CRC32 forgery: encrypted files match original fl.dat checksums.", "success")

    # --- Phase 7: Convert (raw ext4 → partclone) ---

    def _phase_convert(self):
        """Convert modified ext4 image to partclone format for Clonezilla ISO."""
        self.log("Converting modified image to partclone format...", "info")

        # The ext4 image must be unmounted before partclone can read it.
        # Also run e2fsck to fix any metadata inconsistencies from the
        # read-write mount + file modifications.
        if self.mount_point:
            # Clean up build artifacts from /tmp inside the chroot BEFORE
            # unmounting, so they don't end up in the partclone image.
            self.log("Cleaning build artifacts from image...", "info")
            mp = self.mount_point
            for artifact in [
                f"{mp}/tmp/jjp_encrypt.c",
                f"{mp}/tmp/jjp_encrypt.o",
                f"{mp}/tmp/jjp_encrypt.so",
                f"{mp}/tmp/jjp_manifest.txt",
                f"{mp}/tmp/jjp_replacements",
                f"{mp}/tmp/stubs",
            ]:
                try:
                    self.executor.run(f"rm -rf '{artifact}' 2>/dev/null; true", timeout=5)
                except CommandError:
                    pass

            self.log("Unmounting ext4 for conversion...", "info")
            # Unmount bind mounts first (reverse order)
            for target in reversed(self._bind_mounted):
                try:
                    self.executor.run(
                        f"umount -l '{self.mount_point}{target}' 2>/dev/null; true",
                        timeout=10,
                    )
                except CommandError:
                    pass
            self._bind_mounted = []
            # Unmount the ext4
            try:
                self.executor.run(
                    f"umount '{self.mount_point}'", timeout=30)
            except CommandError:
                self.executor.run(
                    f"umount -l '{self.mount_point}' 2>/dev/null; true",
                    timeout=30,
                )
            try:
                self.executor.run(
                    f"rmdir '{self.mount_point}' 2>/dev/null; true", timeout=5)
            except CommandError:
                pass
            self.mount_point = None

        wsl_img = self._raw_img_path

        # Flush and verify the raw image survived
        try:
            self.executor.run("sync", timeout=120)
        except CommandError:
            pass  # sync timeout is not fatal — check file existence next
        try:
            stat_out = self.executor.run(
                f"stat --format='%s bytes, inode %i' '{wsl_img}' 2>&1",
                timeout=10).strip()
            self.log(f"  Raw image: {stat_out}", "info")
        except CommandError as e:
            try:
                loops = self.executor.run(
                    "losetup -a 2>/dev/null || true", timeout=5).strip()
                if loops:
                    self.log(f"  Active loop devices: {loops}", "info")
            except CommandError:
                pass
            raise PipelineError("Convert",
                f"Raw image not found after unmount: {wsl_img}\n"
                f"stat output: {e.output}\n\n"
                "This may be caused by WSL2 discarding cached data "
                "during unmount. Please try running the mod pipeline again.")

        self.log("Running e2fsck to repair filesystem metadata...", "info")
        try:
            for line in self.executor.stream(
                f"e2fsck -fy '{wsl_img}' 2>&1",
                timeout=300,
            ):
                clean = line.strip()
                if clean:
                    self.log(f"  {clean}", "info")
        except CommandError:
            pass  # e2fsck returns non-zero if it made repairs — that's fine

        # Ensure required tools are available
        self._ensure_iso_tools()

        # Mount the original ISO if not already mounted, or re-mount if
        # the previous mount was cleaned up (e.g. by systemd-tmpfiles-clean).
        if self._iso_mount:
            try:
                self.executor.run(
                    f"mountpoint -q '{self._iso_mount}'", timeout=5)
            except CommandError:
                self.log("ISO mount disappeared, re-mounting...", "info")
                self._iso_mount = None

        if not self._iso_mount:
            wsl_iso = self.executor.to_exec_path(self.image_path)
            tag = uuid.uuid4().hex[:8]
            self._iso_mount = f"/var/tmp/jjp_iso_{tag}"
            try:
                self.executor.run(f"mkdir -p {self._iso_mount}", timeout=10)
                self.executor.run(
                    f"mount -o loop,ro '{wsl_iso}' {self._iso_mount}",
                    timeout=config.MOUNT_TIMEOUT,
                )
            except CommandError as e:
                raise PipelineError("Convert",
                    f"Failed to mount original ISO: {e.output}") from e

        # Verify Clonezilla structure
        partimag = f"{self._iso_mount}{config.PARTIMAG_PATH}"
        part_prefix = f"{partimag}/{config.GAME_PARTITION}.ext4-ptcl-img.gz"
        try:
            parts_out = self.executor.run(
                f"ls -1 {part_prefix}.* 2>/dev/null | sort", timeout=10)
        except CommandError:
            parts_out = ""
        parts = [p.strip() for p in parts_out.strip().split("\n") if p.strip()]
        if not parts:
            raise PipelineError("Convert",
                f"No partclone image for {config.GAME_PARTITION} found in ISO.")

        # Determine split size from original files — use exact byte count
        # to match the original chunk boundaries precisely.
        # (JJP originals use 1,000,000,000 bytes, NOT 1 GiB.)
        split_size = "1000000000"
        try:
            sz = self.executor.run(
                f"stat -c%s '{parts[0]}'", timeout=5).strip()
            split_size = sz  # exact byte count from original first chunk
        except (CommandError, ValueError):
            pass
        self.log(f"Using split size: {split_size} bytes", "info")

        # Prefer pigz (parallel gzip) for speed.
        # Use --fast -b 1024 --rsyncable to match the original Clonezilla
        # compression flags, ensuring maximum compatibility.
        try:
            self.executor.run("which pigz", timeout=5)
            compressor = "pigz -c --fast -b 1024 --rsyncable"
        except CommandError:
            compressor = "gzip -c --fast --rsyncable"

        # Run the conversion pipeline — output to a temp chunks directory.
        # The build phase will splice these into the original ISO.
        tag = uuid.uuid4().hex[:8]
        self._chunks_dir = f"/var/tmp/jjp_chunks_{tag}"
        output_prefix = f"{self._chunks_dir}/{config.GAME_PARTITION}.ext4-ptcl-img.gz."
        self.executor.run(f"mkdir -p '{self._chunks_dir}'", timeout=10)

        # The raw image may still be mounted — use the path directly
        wsl_img = self._raw_img_path
        self.log(f"Converting {wsl_img} to partclone format...", "info")
        self.log("This may take 10-30 minutes depending on image size.", "info")

        # Build a wrapper script that runs the conversion in the background
        # and monitors progress from the partclone log file. This lets us
        # stream progress updates to the GUI during the long-running conversion.
        # Note: partclone writes progress with \r (carriage returns) to stderr,
        # so we use tr to convert \r to \n for grep, and stdbuf to reduce
        # buffering on the stderr redirect.
        convert_cmd = (
            f"set -o pipefail && "
            f"partclone.ext4 -c -s '{wsl_img}' -o - 2> >(stdbuf -oL tr '\\r' '\\n' > /var/tmp/jjp_ptcl.log) "
            f"| {compressor} "
            f"| split -b {split_size} -a 2 - '{output_prefix}'"
        )
        monitor_script = (
            f"#!/bin/bash\n"
            f"# Run conversion in background\n"
            f"({convert_cmd}) &\n"
            f"PID=$!\n"
            f"LAST_PCT=-1\n"
            f"# Monitor progress from partclone log\n"
            f"while kill -0 $PID 2>/dev/null; do\n"
            f"  sleep 3\n"
            f"  # Extract latest progress from partclone log\n"
            f"  PCT=$(grep -oP 'Completed:\\s*\\K[\\d.]+' /var/tmp/jjp_ptcl.log 2>/dev/null | tail -1)\n"
            f"  # Get output size\n"
            f"  OSIZE=$(du -sb '{output_prefix}'* 2>/dev/null | awk '{{s+=$1}} END {{printf \"%d\", s}}')\n"
            f"  if [ -n \"$PCT\" ]; then\n"
            f"    # Only print if progress changed\n"
            f"    CUR=$(printf '%.0f' \"$PCT\" 2>/dev/null || echo 0)\n"
            f"    if [ \"$CUR\" != \"$LAST_PCT\" ]; then\n"
            f"      LAST_PCT=$CUR\n"
            f"      echo \"PROGRESS:${{PCT}}% output=${{OSIZE:-0}}\"\n"
            f"    fi\n"
            f"  else\n"
            f"    # No progress yet — show indeterminate\n"
            f"    echo \"PROGRESS:0% output=${{OSIZE:-0}}\"\n"
            f"  fi\n"
            f"done\n"
            f"wait $PID\n"
            f"exit $?\n"
        )
        monitor_path = "/var/tmp/jjp_convert_monitor.sh"
        monitor_b64 = base64.b64encode(monitor_script.encode()).decode()
        self.executor.run(
            f"echo '{monitor_b64}' | base64 -d > {monitor_path} && "
            f"chmod +x {monitor_path}",
            timeout=10,
        )

        self.log("Starting partclone conversion pipeline...", "info")
        last_pct = -1
        try:
            for line in self.executor.stream(
                f"bash {monitor_path}", timeout=config.ISO_CONVERT_TIMEOUT
            ):
                if self.cancelled:
                    self.executor.kill()
                    raise PipelineError("Convert", "Cancelled by user.")
                clean = line.strip()
                if not clean:
                    continue
                m = re.search(r'PROGRESS:([\d.]+)%\s*output=(\d+)', clean)
                if m:
                    pct = float(m.group(1))
                    ipct = int(pct)
                    out_mb = int(m.group(2)) / (1024**2)
                    if ipct > last_pct:
                        last_pct = ipct
                        self.on_progress(ipct, 100, f"{ipct}% ({out_mb:.0f} MB written)")
                        if ipct % 10 == 0:
                            self.log(f"  Conversion: {ipct}% ({out_mb:.0f} MB written)", "info")

        except CommandError as e:
            # Try to read the partclone log for details
            log_content = ""
            try:
                log_content = self.executor.run(
                    "tail -5 /var/tmp/jjp_ptcl.log 2>/dev/null", timeout=5).strip()
            except CommandError:
                pass
            raise PipelineError("Convert",
                f"Partclone conversion failed: {e.output}\n{log_content}") from e

        # Verify output files
        try:
            parts_out = self.executor.run(
                f"ls -lh '{output_prefix}'* 2>/dev/null", timeout=10).strip()
            self.log(f"Partclone files created:\n{parts_out}", "success")
        except CommandError:
            raise PipelineError("Convert", "No partclone output files were created.")

        self.on_progress(100, 100, "Conversion complete")

    def _ensure_iso_tools(self):
        """Ensure partclone and xorriso are available, installing if needed."""
        for tool, pkg in [("partclone.ext4", "partclone"), ("xorriso", "xorriso")]:
            try:
                self.executor.run(f"which {tool}", timeout=10)
                self.log(f"  {tool}: found", "info")
            except CommandError:
                self.log(f"  {tool} not found. Installing {pkg}...", "info")
                try:
                    self.executor.run(
                        f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg} 2>&1",
                        timeout=120,
                    )
                    self.log(f"  {pkg} installed.", "success")
                except CommandError as e:
                    raise PipelineError("Convert",
                        f"Failed to install {pkg}: {e.output}\n"
                        f"Run manually: wsl -u root -- apt install {pkg}") from e

        # Log tool versions for diagnostics
        for ver_cmd, label in [
            ("partclone.ext4 --version 2>&1 | head -1", "partclone"),
            ("xorriso --version 2>&1 | head -1", "xorriso"),
            ("pigz --version 2>&1 | head -1", "pigz"),
        ]:
            try:
                ver = self.executor.run(ver_cmd, timeout=5).strip()
                self.log(f"  {label}: {ver}", "info")
            except CommandError:
                pass

    # --- Phase 8: Build ISO ---

    def _phase_build_iso(self):
        """Assemble modified Clonezilla ISO by splicing new partition chunks
        into the original ISO.  Uses xorriso -indev/-outdev with
        -boot_image any replay to perfectly preserve the original boot
        configuration (MBR, El Torito, EFI, Syslinux)."""
        import os
        self.log("Building modified Clonezilla ISO...", "info")

        iso_basename = os.path.splitext(os.path.basename(self.image_path))[0]
        wsl_out = self.executor.to_exec_path(self.assets_folder)
        output_iso = f"{wsl_out}/{iso_basename}_modified.iso"
        wsl_iso = self.executor.to_exec_path(self.image_path)

        # Enumerate new chunk files produced by _phase_convert
        chunks_dir = self._chunks_dir
        game_part = config.GAME_PARTITION
        partimag = config.PARTIMAG_PATH
        try:
            chunks_out = self.executor.run(
                f"ls -1 '{chunks_dir}/{game_part}.ext4-ptcl-img.gz.'* "
                f"2>/dev/null | sort",
                timeout=10,
            ).strip()
        except CommandError:
            chunks_out = ""
        new_chunks = [c.strip() for c in chunks_out.split("\n") if c.strip()]
        if not new_chunks:
            raise PipelineError("Build ISO", "No new partition chunks found.")
        self.log(f"Found {len(new_chunks)} new partition chunk(s).", "info")

        # Build xorriso command:
        #   -indev  : read original ISO (preserves all structure)
        #   -outdev : write modified ISO
        #   -boot_image any replay : preserve ALL boot records from original
        #   -find … -exec remove   : delete old partition chunks
        #   -map …                 : add new partition chunks
        rm_cmd = (
            f"-find '{partimag}' "
            f"-name '{game_part}.ext4-ptcl-img.gz.*' "
            f"-exec rm --"
        )

        map_cmds = []
        for chunk_path in new_chunks:
            base = chunk_path.rsplit("/", 1)[-1]
            iso_path = f"{partimag}/{base}"
            map_cmds.append(f"-map '{chunk_path}' '{iso_path}'")

        map_str = " \\\n  ".join(map_cmds)

        script = (
            f"#!/bin/bash\n"
            f"set -e\n"
            f"xorriso \\\n"
            f"  -indev '{wsl_iso}' \\\n"
            f"  -outdev '{output_iso}' \\\n"
            f"  -boot_image any replay \\\n"
            f"  {rm_cmd} \\\n"
            f"  {map_str} \\\n"
            f"  -end 2>&1\n"
        )
        script_path = "/var/tmp/jjp_build_iso.sh"
        script_b64 = base64.b64encode(script.encode()).decode()
        self.executor.run(
            f"echo '{script_b64}' | base64 -d > {script_path} && "
            f"chmod +x {script_path}",
            timeout=10,
        )

        # Unmount/remove the original ISO before xorriso reads it — avoids
        # contention between the loop mount and xorriso's file access.
        if self._iso_mount:
            try:
                if getattr(self, '_iso_mounted', False):
                    self.executor.run(
                        f"umount -l '{self._iso_mount}' 2>/dev/null; true", timeout=15)
                self.executor.run(
                    f"rm -rf '{self._iso_mount}' 2>/dev/null; true", timeout=15)
            except CommandError:
                pass
            self._iso_mount = None

        # Remove existing output ISO — xorriso refuses to write to non-empty -outdev
        try:
            self.executor.run(f"rm -f '{output_iso}'", timeout=10)
        except CommandError:
            pass

        self.log("Running xorriso (splicing partition into original ISO)...", "info")
        last_pct = -1
        try:
            for line in self.executor.stream(
                f"bash {script_path}", timeout=config.ISO_BUILD_TIMEOUT
            ):
                self._check_cancel()
                clean = line.strip()
                if not clean:
                    continue
                if re.search(r"FAILURE|SORRY|FATAL|ABORT|error|cannot|"
                             r"No space|not found|Killed",
                             clean, re.IGNORECASE):
                    self.log(f"  xorriso: {clean}", "error")
                # xorriso native mode: "Writing:  1234s    12.3%"
                m = re.search(r'(\d+\.\d+)%', clean)
                if m:
                    pct = int(float(m.group(1)))
                    if pct > last_pct:
                        last_pct = pct
                        self.on_progress(pct, 100, f"Building ISO: {pct}%")
        except CommandError as e:
            try:
                script_content = self.executor.run(
                    f"cat {script_path}", timeout=5).strip()
                self.log(f"Build script was:\n{script_content}", "info")
            except CommandError:
                pass
            detail = (e.output or "").strip() or "(no output captured)"
            hint = ""
            if e.returncode == 137:
                hint = ("\n\nExit 137 means the process was killed — usually "
                        "the container ran out of memory. Increase the "
                        "Docker Desktop memory limit and try again.")
            elif "no space left" in detail.lower():
                hint = ("\n\nThe output drive is full. Free up disk space "
                        "and try again.")
            raise PipelineError("Build ISO",
                f"xorriso failed (exit {e.returncode}):\n{detail}{hint}") from e

        # Verify output and compare size with original
        try:
            new_sz = int(self.executor.run(
                f"stat -c%s '{output_iso}'", timeout=10).strip())
            orig_sz = int(self.executor.run(
                f"stat -c%s '{wsl_iso}'", timeout=10).strip())
            new_gb = new_sz / (1024**3)
            orig_gb = orig_sz / (1024**3)
            diff_mb = (new_sz - orig_sz) / (1024**2)
            self.log(
                f"ISO created: {new_gb:.2f} GB "
                f"(original: {orig_gb:.2f} GB, diff: {diff_mb:+.1f} MB)",
                "success",
            )
        except (CommandError, ValueError):
            raise PipelineError("Build ISO", "ISO file was not created.")

        win_iso_path = os.path.join(self.assets_folder, f"{iso_basename}_modified.iso")
        self._output_iso_path = win_iso_path
        self.log(f"Output ISO: {win_iso_path}", "success")

        # Verify the modified ISO actually contains different partition data
        self.on_progress(0, 0, "Verifying ISO...")
        self._verify_iso_partition(output_iso, wsl_iso, partimag, game_part)
        self.on_progress(100, 100, "ISO build complete")

    def _verify_iso_partition(self, output_iso, orig_iso, partimag, game_part):
        """Verify the modified ISO has different partition data than the original.

        Compares MD5 of the first partition chunk between original and modified
        ISOs to confirm xorriso actually replaced the data.
        """
        import uuid as _uuid
        tag = _uuid.uuid4().hex[:8]
        verify_mount = f"/var/tmp/jjp_verify_{tag}"
        try:
            self.executor.run(f"mkdir -p {verify_mount}", timeout=5)
            self.executor.run(
                f"mount -o loop,ro '{output_iso}' {verify_mount}",
                timeout=30)

            chunk_name = f"{game_part}.ext4-ptcl-img.gz.aa"
            new_chunk = f"{verify_mount}{partimag}/{chunk_name}"
            # orig_iso might already be unmounted, so re-mount temporarily
            orig_mount = f"/var/tmp/jjp_orig_{tag}"
            self.executor.run(f"mkdir -p {orig_mount}", timeout=5)
            self.executor.run(
                f"mount -o loop,ro '{orig_iso}' {orig_mount}",
                timeout=30)
            orig_chunk = f"{orig_mount}{partimag}/{chunk_name}"

            new_md5 = self.executor.run(
                f"md5sum '{new_chunk}' | cut -d' ' -f1", timeout=300).strip()
            orig_md5 = self.executor.run(
                f"md5sum '{orig_chunk}' | cut -d' ' -f1", timeout=300).strip()

            self.executor.run(
                f"umount -l '{orig_mount}' 2>/dev/null; "
                f"rmdir '{orig_mount}' 2>/dev/null; true", timeout=15)
            self.executor.run(
                f"umount -l '{verify_mount}' 2>/dev/null; "
                f"rmdir '{verify_mount}' 2>/dev/null; true", timeout=15)

            if new_md5 == orig_md5:
                self.log(
                    "WARNING: Modified ISO partition is IDENTICAL to original!",
                    "error")
                self.log(
                    "Your changes were not included in the final ISO. "
                    "This is likely a problem with xorriso on your system.",
                    "error")
                self.log(
                    "To fix this, try the following:\n"
                    "  1. Run:  wsl -u root -- apt update && "
                    "wsl -u root -- apt install --reinstall xorriso partclone\n"
                    "  2. Run:  wsl --shutdown  (in a Windows terminal)\n"
                    "  3. Re-run Apply Modifications\n"
                    "If the problem persists, please share your full log.",
                    "error")
            else:
                self.log(
                    f"Verified: partition data differs from original "
                    f"(orig={orig_md5[:8]}… new={new_md5[:8]}…)",
                    "success")
        except Exception as e:
            # Verification failure is non-fatal — log and continue
            self.log(f"ISO verification skipped: {e}", "info")
            try:
                self.executor.run(
                    f"umount -l '{verify_mount}' 2>/dev/null; "
                    f"rmdir '{verify_mount}' 2>/dev/null; true", timeout=15)
            except CommandError:
                pass

    # --- Cleanup ---

    def _phase_cleanup(self):
        """Clean up mounts, build dir, and detach dongle."""
        self.log("Cleaning up...", "info")

        if self.mount_point:
            mp = self.mount_point
            try:
                self.executor.run("killall hasplmd_x86_64 2>/dev/null; true", timeout=10)
            except CommandError:
                pass

            usbipd = find_usbipd()
            self.executor.run_win(
                [usbipd, "detach", "--hardware-id", config.HASP_VID_PID],
                timeout=10,
            )

            for target in reversed(self._bind_mounted):
                try:
                    self.executor.run(f"umount -l '{mp}{target}' 2>/dev/null; true", timeout=10)
                except CommandError:
                    pass

            try:
                self.executor.run(f"umount -l '{mp}' 2>/dev/null; true", timeout=30)
            except CommandError:
                pass

            try:
                self.executor.run(f"rmdir '{mp}' 2>/dev/null; true", timeout=5)
            except CommandError:
                pass

        if self._iso_mount:
            try:
                self.executor.run(f"umount -l '{self._iso_mount}' 2>/dev/null; true", timeout=15)
                self.executor.run(f"rmdir '{self._iso_mount}' 2>/dev/null; true", timeout=5)
            except CommandError:
                pass

        # Clean up temp chunks directory
        if hasattr(self, '_chunks_dir') and self._chunks_dir:
            self.log("Removing temp chunks directory...", "info")
            try:
                self.executor.run(f"rm -rf '{self._chunks_dir}'", timeout=60)
            except CommandError:
                self.log(f"Warning: Could not remove {self._chunks_dir}", "info")

        # Clean up partclone log and temp scripts
        try:
            self.executor.run(
                "rm -f /var/tmp/jjp_ptcl.log /var/tmp/jjp_convert_monitor.sh "
                "/var/tmp/jjp_build_iso.sh 2>/dev/null; true", timeout=5)
        except CommandError:
            pass

        self.log("Cleanup complete.", "success")


class StandaloneDecryptPipeline(DecryptionPipeline):
    """Decryption pipeline that uses pure Python crypto instead of dongle/chroot.

    Works completely without a HASP dongle. If fl_dat_path is provided, uses
    the cached file list. Otherwise, scans the filesystem and auto-detects
    filler sizes using magic byte signatures.

    Eliminates: Chroot, Dongle, Compile phases.
    Phases: Extract > Mount > Decrypt > Copy > Cleanup
    """

    def __init__(self, image_path, output_path, fl_dat_path,
                 log_cb, phase_cb, progress_cb, done_cb,
                 full_dump=False, extract_graphics=True,
                 extract_sounds=True):
        super().__init__(image_path, output_path,
                         log_cb, phase_cb, progress_cb, done_cb)
        self.fl_dat_path = fl_dat_path  # can be None for fully dongle-free
        self.full_dump = full_dump
        self.extract_graphics = extract_graphics
        self.extract_sounds = extract_sounds

    @staticmethod
    def _nothing_decrypted_message(walked, scan_found=None):
        """Error text for a decrypt pass that produced no assets at all."""
        detail = ""
        if scan_found == 0:
            detail = ("Every one of them failed the encryption probe — not "
                      "one decoded to a recognisable image, sound or video "
                      "file.\n\n")
        return (
            f"Decrypted 0 of {walked} encrypted asset(s).\n\n"
            f"{detail}"
            "This game build encrypts its assets in a way this version does "
            "not recognise, so there is nothing to show for the run. Newer "
            "game engines change the scheme and support has to be added for "
            "them.\n\n"
            "The unencrypted part of the image still extracts: tick "
            "\"File System\" on the Extract tab to pull the plain files."
        )

    def run(self):
        """Execute the standalone pipeline."""
        import os
        from .executor import DockerExecutor
        cleanup_phase = len(config.STANDALONE_PHASES) - 1
        try:
            self._log_system_diagnostics()

            # Check core prerequisites before starting
            prereq_results = check_prerequisites(self.executor, standalone=True)
            # Decrypt pipeline only needs WSL/Docker/System + partclone + xorriso
            core = {"WSL2", "partclone", "xorriso", "Docker", "System"}
            missing = [(name, msg) for name, passed, msg in prereq_results
                       if not passed and name in core]
            if missing:
                # Surface the per-prereq detail — on macOS partclone/xorriso
                # live inside the Docker image, so a "missing" here usually
                # means the image build or container start failed (the real
                # reason is in the message), not that a tool is absent.
                names = ", ".join(n for n, _ in missing)
                details = "\n".join(f"  {n}: {m}" for n, m in missing if m)
                raise PipelineError("Extract",
                    f"Missing prerequisites: {names}\n"
                    f"{details}\n\n"
                    "Click 'Install Missing' on the main screen to install "
                    "them, or install manually and restart the app.")

            # Verify both paths are accessible from the executor
            for label, path in [("Game image", self.image_path),
                                ("Output folder", self.output_path)]:
                ok, msg = self.executor.check_path_accessible(path)
                if not ok:
                    raise PipelineError("Extract", f"{label} path error:\n{msg}")

            # Start Docker container if on macOS
            if isinstance(self.executor, DockerExecutor):
                self.log("Starting Docker container...", "info")
                cache_dir = self.executor._cache_dir()
                self._docker_partclone_path = _stage_project_file(
                    "partclone_to_raw.py", cache_dir)
                self.executor.start_container([
                    self.image_path, self.output_path])

            self.on_phase(0)  # Extract
            self._phase_extract()
            self._check_cancel()

            self.on_phase(1)  # Mount
            self._phase_mount()
            self._check_cancel()

            # Detect game name from the mount
            self._detect_game()

            self.on_phase(2)  # Decrypt
            if self.extract_graphics or self.extract_sounds:
                self._phase_decrypt_standalone()
            else:
                self.log("Skipping asset decryption (no graphics/sounds selected).",
                         "info")
            self._check_cancel()

            # Full filesystem dump (if requested)
            if self.full_dump:
                self._phase_copy_full_filesystem()
                self._check_cancel()

            # Generate checksums AFTER all files (assets + system) are in
            # the output folder, so the mod pipeline can detect changes to
            # any of them.
            wsl_out = self.executor.to_exec_path(self.output_path)
            self._generate_checksums(wsl_out)

            self._succeeded = True
            self.on_phase(cleanup_phase)  # Cleanup
            self._phase_cleanup_standalone()
            self.on_done(True, f"Decryption complete! Files saved to:\n{self.output_path}")

        except PipelineError as e:
            self.log(str(e), "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup_standalone()
            self.on_done(False, str(e))
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup_standalone()
            self.on_done(False, f"Unexpected error: {e}")

    def _detect_game(self):
        """Detect game name from mount point (simplified, no chroot setup)."""
        self.log("Scanning for game...", "info")
        try:
            result = self.executor.run(
                f"ls -1 {self.mount_point}{config.GAME_BASE_PATH}/",
                timeout=15,
            )
        except CommandError as e:
            raise PipelineError("Mount",
                f"No JJP game found at {config.GAME_BASE_PATH}/") from e

        for name in result.strip().split("\n"):
            name = name.strip()
            if not name:
                continue
            game_path = f"{self.mount_point}{config.GAME_BASE_PATH}/{name}/game"
            try:
                self.executor.run(f"test -f '{game_path}'", timeout=5)
                self.game_name = name
                display = config.KNOWN_GAMES.get(name, name)
                self.log(f"Detected game: {display} ({name})", "success")
                return
            except CommandError:
                pass

    def _phase_decrypt_standalone(self):
        """Decrypt all files using pure Python crypto, running inside WSL.

        Deploys crypto.py and filelist.py to WSL /tmp/ and runs a single
        Python process that reads encrypted files from the mounted ext4
        and writes decrypted output — avoiding per-file cross-OS overhead.

        Supports two modes:
        - With fl_dat_path: uses cached file list (fast)
        - Without fl_dat_path: scans filesystem and auto-detects filler sizes
        """
        import os

        mp = self.mount_point
        wsl_out = self.executor.to_exec_path(self.output_path)
        self.executor.run(f"mkdir -p '{wsl_out}'", timeout=10)

        # Deploy crypto module to WSL /tmp
        self.log("Deploying Python crypto module to WSL...", "info")
        from .executor import DockerExecutor
        if isinstance(self.executor, DockerExecutor):
            # Docker on macOS: write module source into cache dir (mounted
            # as /tmp).  Read via pkgutil.get_data, which works for both
            # source installs and PyInstaller bundles (--add-data files).
            # The package is pinball_decryptor.plugins.jjp — NOT the old
            # standalone repo's "jjp_decryptor".  get_data returns None
            # (it does not raise) when the package/resource is missing, and
            # writing that None used to crash with the opaque "a bytes-like
            # object is required, not 'NoneType'" — so resolve the right
            # package, fall back to the colocated source file, and guard.
            import pkgutil
            pkg = __package__ or "pinball_decryptor.plugins.jjp"
            this_dir = os.path.dirname(os.path.abspath(__file__))
            cache_dir = self.executor._cache_dir()
            for module in ("crypto.py", "filelist.py"):
                data = pkgutil.get_data(pkg, module)
                if data is None:
                    # Fallback: read the .py sitting next to this file
                    # (source installs, and onedir bundles that keep it).
                    src = os.path.join(this_dir, module)
                    if os.path.isfile(src):
                        with open(src, "rb") as f:
                            data = f.read()
                if data is None:
                    raise PipelineError("Decrypt",
                        f"Could not load {module} to deploy into the "
                        f"decryption container — this is a packaging bug. "
                        f"Please report it with your app version.")
                dst = os.path.join(cache_dir, f"jjp_{module}")
                with open(dst, "wb") as f:
                    f.write(data)
        else:
            pkg_dir = os.path.dirname(os.path.abspath(__file__))
            for module in ("crypto.py", "filelist.py"):
                src = self.executor.to_exec_path(os.path.join(pkg_dir, module))
                self.executor.run(f"cp '{src}' /tmp/jjp_{module}", timeout=10)

        has_fl_dat = self.fl_dat_path and os.path.isfile(self.fl_dat_path)

        if has_fl_dat:
            # Copy cached fl.dat (skip if already in the output folder)
            wsl_fl = self.executor.to_exec_path(self.fl_dat_path)
            wsl_fl_dest = f"{wsl_out}/fl_decrypted.dat"
            if os.path.normpath(os.path.abspath(self.fl_dat_path)) != \
               os.path.normpath(os.path.join(self.output_path, "fl_decrypted.dat")):
                self.executor.run(
                    f"cp '{wsl_fl}' '{wsl_fl_dest}'", timeout=10)
            self.executor.run(
                f"cp '{wsl_fl}' /tmp/fl_decrypted.dat", timeout=10)
            self.log("Using cached fl_decrypted.dat", "info")
        else:
            self.log(
                "No fl_decrypted.dat found. Scanning filesystem to "
                "auto-detect filler sizes (dongle-free mode)...", "info")

        # Build the decrypt script — writes directly to Windows output folder
        game_name = self.game_name or ""
        edata_dir = f"{mp}{config.GAME_BASE_PATH}/{game_name}/edata"

        script = _DECRYPT_SCRIPT.format(
            has_fl_dat="True" if has_fl_dat else "False",
            mp=mp,
            out_dir=wsl_out,
            edata_dir=edata_dir,
            game_name=game_name,
            extract_graphics="True" if self.extract_graphics else "False",
            extract_sounds="True" if self.extract_sounds else "False",
        )

        # Write script to WSL /tmp
        import base64 as _b64
        script_b64 = _b64.b64encode(script.encode()).decode()
        self.executor.run(
            f"echo '{script_b64}' | base64 -d > /tmp/jjp_decrypt_run.py",
            timeout=10)

        cmd = "PYTHONUNBUFFERED=1 python3 /tmp/jjp_decrypt_run.py 2>&1"

        total_files = 0
        final_ok = 0
        final_fail = 0
        final_total = 0

        scan_found = None

        total_re = re.compile(r'TOTAL_FILES=(\d+)')
        scan_re = re.compile(r'Scan complete:\s*(\d+)\s+files found')
        progress_re = re.compile(
            r'Progress:\s*(\d+)\s*\(ok=(\d+)\s+fail=(\d+)\s+skip=(\d+)\)')
        result_re = re.compile(
            r'Total:\s*(\d+)\s+OK:\s*(\d+)\s+Failed:\s*(\d+)\s+Skipped:\s*(\d+)')

        try:
            for line in self.executor.stream(cmd, timeout=config.DECRYPT_TIMEOUT):
                if self.cancelled:
                    self.executor.kill()
                    raise PipelineError("Decrypt", "Cancelled by user.")

                level = "info"
                if "[FAIL]" in line:
                    level = "error"

                m = total_re.search(line)
                if m:
                    total_files = int(m.group(1))
                    self.on_progress(0, total_files, "Decrypting...")

                m = scan_re.search(line)
                if m:
                    scan_found = int(m.group(1))

                m = progress_re.search(line)
                if m:
                    current = int(m.group(1))
                    ok = int(m.group(2))
                    fail = int(m.group(3))
                    skip = int(m.group(4))
                    desc = f"ok={ok} fail={fail} skip={skip}"
                    self.on_progress(current, total_files, desc)

                m = result_re.search(line)
                if m:
                    final_total = int(m.group(1))
                    final_ok = int(m.group(2))
                    final_fail = int(m.group(3))

                self.log(line, level)

        except CommandError as e:
            if final_total > 0:
                pass
            else:
                raise PipelineError("Decrypt",
                    f"Decryption process failed: {e.output}") from e

        if final_total == 0 and total_files == 0:
            raise PipelineError("Decrypt",
                "No files were decrypted. Check fl_decrypted.dat path mapping.")

        # Walking thousands of encrypted assets and decrypting none of them is
        # a failure, not a "complete" run — without this the GUI reported
        # success over an empty output folder.  Only the categories the user
        # actually asked for count: unticking both Graphics and Sounds
        # legitimately leaves nothing to decrypt.
        if (final_ok == 0 and total_files > 0
                and (self.extract_graphics or self.extract_sounds)):
            raise PipelineError("Decrypt",
                self._nothing_decrypted_message(total_files, scan_found))

        self.on_progress(final_total, final_total, "Complete")
        self.log(
            f"Decryption finished: {final_ok} OK, {final_fail} failed "
            f"out of {final_total} files.",
            "success" if final_fail == 0 else "info",
        )
        # The decrypt workers wrote .checksums.edata.md5 (MD5 of every
        # decrypted file) — tell the checksum phase to merge it instead of
        # re-hashing the assets off disk.
        self._edata_checksum_partial = True

    def _phase_copy_full_filesystem(self):
        """Copy all non-edata files from the mounted filesystem to output/system/.

        These files are NOT encrypted — they include the game binary, scripts,
        shared libraries, OS configs, kernel modules, etc.  They are not listed
        in fl.dat, so no CRC checks apply.

        Uses tar streaming instead of rsync for much faster cross-filesystem
        transfer (single pipe vs thousands of individual file writes across
        the WSL→NTFS bridge).
        """
        self.log("Copying full filesystem (non-asset files)...", "info")
        mp = self.mount_point
        wsl_out = self.executor.to_exec_path(self.output_path)
        sys_out = f"{wsl_out}/system"

        self.executor.run(f"mkdir -p '{sys_out}'", timeout=10)

        game = self.game_name or ""
        edata_rel = f"jjpe/gen1/{game}/edata"
        self.log(f"  Mount point: {mp}", "info")
        self.log(f"  Game name: {game or '(not detected)'}", "info")
        self.log(f"  Excluding edata at: {edata_rel}", "info")

        # Log top-level contents for diagnostics
        try:
            top_ls = self.executor.run(
                f"ls -1 '{mp}/' 2>/dev/null | head -30", timeout=10).strip()
            self.log(f"  Mount root contents: {top_ls.replace(chr(10), ', ')}",
                     "info")
        except CommandError:
            self.log("  Warning: could not list mount root", "info")

        # Exclude edata (already decrypted) and Linux virtual/special dirs
        # that can't be copied to NTFS
        excludes = [edata_rel, "proc", "sys", "dev", "run", "tmp",
                    "lost+found"]

        # Count all filesystem entries (files, symlinks, dirs) for accurate
        # progress — tar xvf outputs all of them, not just regular files.
        prune_args = " ".join(
            f"-path '{mp}/{d}' -prune -o" for d in excludes)
        try:
            total_str = self.executor.run(
                f"find '{mp}/' {prune_args} "
                f"-print 2>/dev/null | wc -l",
                timeout=30).strip()
            total_entries = int(total_str)
        except (CommandError, ValueError):
            total_entries = 0

        if total_entries > 0:
            self.log(f"Found {total_entries} system entries to copy.", "info")
        self.on_progress(0, total_entries or 1, "Copying system files...")

        # tar pipe: archive everything except excluded dirs, stream straight
        # to extraction at the destination.  Much faster than rsync/cp for
        # large file counts across the WSL→NTFS filesystem bridge.
        # Use verbose extract (tar xvf) to get per-entry progress via stream().
        tar_excludes = " ".join(
            f"--exclude='./{d}'" for d in excludes)
        # --warning is GNU tar only; detect before using
        tar_warn = ""
        try:
            self.executor.run(
                "tar --warning=no-file-changed -cf /dev/null /dev/null "
                "2>/dev/null", timeout=5)
            tar_warn = "--warning=no-file-changed "
        except CommandError:
            pass
        tar_cmd = (
            f"cd '{mp}' && tar cf - "
            f"{tar_excludes} "
            f"{tar_warn}"
            f". 2>/tmp/jjp_tar_err.log "
            f"| tar xvf - -C '{sys_out}/' 2>&1; true"
        )
        try:
            copied = 0
            for line in self.executor.stream(
                tar_cmd, timeout=config.COPY_TIMEOUT,
            ):
                self._check_cancel()
                if line.strip():
                    copied += 1
                    if total_entries > 0 and copied % 200 == 0:
                        pct = min(int(copied * 100 / total_entries), 99)
                        self.on_progress(
                            min(copied, total_entries), total_entries,
                            f"Copying system files ({pct}%)")
        except CommandError:
            self.log("Some files could not be copied (permission errors "
                     "or special files skipped).", "info")

        # Report any tar errors for diagnostics
        if copied == 0:
            try:
                tar_err = self.executor.run(
                    "cat /tmp/jjp_tar_err.log 2>/dev/null | head -20",
                    timeout=10).strip()
                if tar_err:
                    self.log(f"tar create errors: {tar_err}", "info")
            except CommandError:
                pass
            # Also check if the extract side had issues
            try:
                test = self.executor.run(
                    f"ls -la '{sys_out}/' 2>&1 | head -5",
                    timeout=10).strip()
                self.log(f"sys_out contents: {test}", "info")
            except CommandError:
                pass

        self.on_progress(total_entries or 1, total_entries or 1,
                         "System copy complete")

        # Count and report
        try:
            count = self.executor.run(
                f"find '{sys_out}' -type f | wc -l", timeout=30).strip()
            size = self.executor.run(
                f"du -sh '{sys_out}' | cut -f1", timeout=30).strip()
        except CommandError:
            count, size = "?", "?"

        self.log(f"System dump: {count} files ({size}) saved to system/",
                 "success")

    def _phase_cleanup_standalone(self):
        """Simplified cleanup - no daemon or USB to clean up."""
        self.log("Cleaning up...", "info")

        if self.mount_point:
            try:
                self.executor.run(
                    f"umount -l '{self.mount_point}' 2>/dev/null; true",
                    timeout=30)
            except CommandError:
                pass
            try:
                self.executor.run(
                    f"rmdir '{self.mount_point}' 2>/dev/null; true", timeout=5)
            except CommandError:
                pass

        if self._iso_mount:
            try:
                self.executor.run(
                    f"umount -l '{self._iso_mount}' 2>/dev/null; true",
                    timeout=15)
                self.executor.run(
                    f"rmdir '{self._iso_mount}' 2>/dev/null; true", timeout=5)
            except CommandError:
                pass

        if self._raw_img_path and (self._raw_img_path.startswith("/tmp/") or
                                   self._raw_img_path.startswith("/var/tmp/")):
            try:
                self.executor.run(
                    f"rm -f '{self._raw_img_path}' 2>/dev/null; true",
                    timeout=10)
            except CommandError:
                pass

        # Stop Docker container if applicable
        from .executor import DockerExecutor
        if isinstance(self.executor, DockerExecutor):
            try:
                self.executor.stop_container()
            except Exception:
                pass

        self.log("Cleanup complete.", "success")


class StandaloneModPipeline(ModPipeline):
    """Mod pipeline using pure Python crypto instead of dongle/chroot.

    Requires a previously-cached fl_decrypted.dat.
    Eliminates: Chroot, Dongle, Compile phases.
    Phases: Scan > Extract > Mount > Encrypt > Convert > Build ISO > Cleanup
    """

    def __init__(self, image_path, assets_folder, fl_dat_path,
                 log_cb, phase_cb, progress_cb, done_cb,
                 skip_duration_match=False, keep_full_length_paths=None):
        super().__init__(image_path, assets_folder,
                         log_cb, phase_cb, progress_cb, done_cb)
        self.fl_dat_path = fl_dat_path
        self.skip_duration_match = skip_duration_match
        # Per-slot exemptions from the trim-to-original-length: rel paths
        # (forward-slashed, relative to the assets folder — same keys the GUI
        # uses) whose replacement should keep its own full length instead of
        # being trimmed/padded to the original slot.  See _resize_*_to_duration.
        self.keep_full_length_paths = frozenset(keep_full_length_paths or ())

    def run(self):
        """Execute the standalone mod pipeline."""
        import os
        from .executor import DockerExecutor
        cleanup_phase = len(config.STANDALONE_MOD_PHASES) - 1
        try:
            self._log_system_diagnostics()

            # Check all prerequisites before starting
            prereq_results = check_prerequisites(self.executor, standalone=True)
            missing = _mod_blocking_prereqs(self.executor, prereq_results)
            if missing:
                # Surface the per-prereq detail — on macOS partclone/xorriso
                # live inside the Docker image, so a "missing" here usually
                # means the image build or container start failed (the real
                # reason is in the message), not that a tool is absent.
                names = ", ".join(n for n, _ in missing)
                details = "\n".join(f"  {n}: {m}" for n, m in missing if m)
                raise PipelineError("Scan",
                    f"Missing prerequisites: {names}\n"
                    f"{details}\n\n"
                    "Click 'Install Missing' on the main screen to install "
                    "them, or install manually and restart the app.")

            # Verify both paths are accessible from the executor
            for label, path in [("Game image", self.image_path),
                                ("Assets folder", self.assets_folder)]:
                ok, msg = self.executor.check_path_accessible(path)
                if not ok:
                    raise PipelineError("Scan", f"{label} path error:\n{msg}")

            # Start Docker container if on macOS
            if isinstance(self.executor, DockerExecutor):
                self.log("Starting Docker container...", "info")
                cache_dir = self.executor._cache_dir()
                self._docker_partclone_path = _stage_project_file(
                    "partclone_to_raw.py", cache_dir)
                self.executor.start_container([
                    self.image_path, self.assets_folder])

            self.on_phase(0)  # Scan
            self._phase_scan()
            self._check_cancel()

            if not self.changed_files:
                self.on_done(True,
                    "No changes detected in the assets folder.\n"
                    "Modify files in the output folder and try again.")
                return

            self.on_phase(1)  # Extract
            self._timed("Extract", self._phase_extract)
            self._check_cancel()

            self.on_phase(2)  # Mount
            self._phase_mount_rw()
            self._check_cancel()

            self.on_phase(3)  # Encrypt
            self._timed("Encrypt", self._phase_encrypt_standalone)
            self._check_cancel()

            if self._is_iso():
                self.on_phase(4)  # Convert
                self._timed("Convert", self._phase_convert_standalone)
                self._check_cancel()

                self.on_phase(5)  # Build ISO
                self._timed("Build ISO", self._phase_build_iso)
                self._check_cancel()

            self._succeeded = True
            self.on_phase(cleanup_phase)
            self._phase_cleanup_standalone()

            if self._is_iso() and hasattr(self, '_output_iso_path'):
                win_path = self._output_iso_path
                self.log(f"Modified ISO ready at: {win_path}", "success")
                self.on_done(True,
                    f"Asset modification complete!\n"
                    f"Modified ISO at:\n{win_path}")
                self.log("", "info")
                self.log("=== Next Steps ===", "info")
                if sys.platform == "win32":
                    self.log(
                        "1. Write this ISO to a USB drive using Rufus\n"
                        "   Important: select ISO mode (NOT DD mode) when prompted\n"
                        "2. Boot the pinball machine from USB\n"
                        "3. Let Clonezilla restore the image to the machine",
                        "info",
                    )
                    self.log_link(
                        "JJP USB Update Instructions (PDF)",
                        "https://marketing.jerseyjackpinball.com/general/install-full/"
                        "JJP_USB_UPDATE_PC_instructions.pdf",
                    )
                else:
                    self.log(
                        "1. Write this ISO to a USB drive using balenaEtcher or dd\n"
                        "2. Boot the pinball machine from USB\n"
                        "3. Let Clonezilla restore the image to the machine",
                        "info",
                    )
                    if sys.platform == "darwin":
                        self.log_link(
                            "JJP USB Update Instructions for Mac (PDF)",
                            "https://marketing.jerseyjackpinball.com/general/install-full/"
                            "JJP_USB_UPDATE_MAC_instructions.pdf",
                        )
                    else:
                        self.log_link(
                            "JJP USB Update Instructions (PDF)",
                            "https://marketing.jerseyjackpinball.com/general/install-full/"
                            "JJP_USB_UPDATE_PC_instructions.pdf",
                        )
            else:
                img_name = (self._raw_img_path.rsplit("/", 1)[-1]
                            if self._raw_img_path else "image")
                wsl_out = self.executor.to_exec_path(self.assets_folder)
                dest = f"{wsl_out}/{img_name}"
                win_path = os.path.join(self.assets_folder, img_name)
                if self._raw_img_path and self._raw_img_path != dest:
                    self.log("Moving modified image to output folder...", "info")
                    try:
                        for line in self.executor.stream(
                            f"rsync --info=progress2 --no-inc-recursive "
                            f"--remove-source-files "
                            f"'{self._raw_img_path}' '{dest}'",
                            timeout=config.COPY_TIMEOUT,
                        ):
                            self._check_cancel()
                    except CommandError:
                        pass
                self.log(f"Modified image ready at: {win_path}", "success")
                self.on_done(True,
                    f"Asset modification complete!\n"
                    f"Modified image at:\n{win_path}")

        except PipelineError as e:
            self.log(str(e), "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup_standalone()
            self.on_done(False, str(e))
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup_standalone()
            self.on_done(False, f"Unexpected error: {e}")

    def _debugfs_dump_file(self, image_file_path, timeout=120):
        """Extract a file from the ext4 image via debugfs dump.

        Returns the file contents as bytes.
        """
        import base64 as _b64

        dump_path = f"{self._debugfs_tmp}/dumped_file"
        self._debugfs_run(
            f'dump "{image_file_path}" "{dump_path}"',
            timeout=timeout,
        )
        enc_b64 = self.executor.run(
            f"base64 '{dump_path}'", timeout=timeout).strip()
        self.executor.run(f"rm -f '{dump_path}'", timeout=5)
        return _b64.b64decode(enc_b64)

    # ---- Phase 2: Prepare (was Mount) ----

    def _phase_mount_rw(self):
        """Prepare ext4 image for direct debugfs modification (no mount)."""
        import uuid as _uuid

        self.log("Preparing ext4 image for modification...", "info")
        if self._raw_img_path:
            wsl_img = self._raw_img_path
        else:
            wsl_img = self.executor.to_exec_path(self.image_path)

        self._wsl_img = wsl_img

        # Clean up any stale mounts from previous (pre-debugfs) runs
        try:
            self._cleanup_stale_mounts(wsl_img)
        except Exception:
            pass

        # Create staging directory for debugfs temp files
        tag = _uuid.uuid4().hex[:8]
        self._debugfs_tmp = f"/var/tmp/jjp_debugfs_{tag}"
        self.executor.run(f"mkdir -p '{self._debugfs_tmp}'", timeout=10)

        # Validate the image is a valid ext4 filesystem
        try:
            self._debugfs_run("stats", timeout=30)
            self.log("ext4 image validated.", "success")
        except CommandError as e:
            raise PipelineError("Prepare",
                f"Image is not a valid ext4 filesystem: {e.output}") from e

        # Detect game name via debugfs ls
        try:
            result = self._debugfs_run(
                f"ls {config.GAME_BASE_PATH}", timeout=15)
            # debugfs ls output: inode (reclen) name
            import re as _re
            for name in _re.findall(r'\(\d+\)\s+(\S+)', result):
                if name in ('.', '..'):
                    continue
                try:
                    stat_out = self._debugfs_run(
                        f'stat "{config.GAME_BASE_PATH}/{name}/game"',
                        timeout=10)
                    if 'Inode:' in stat_out or 'Type: regular' in stat_out:
                        self.game_name = name
                        display = config.KNOWN_GAMES.get(name, name)
                        self.log(f"Detected game: {display} ({name})",
                                 "success")
                        break
                except CommandError:
                    pass
        except CommandError:
            pass

        # No mount point — debugfs operates on the image file directly
        self.mount_point = None
        self.log("Image prepared for debugfs operations.", "success")

    # ------------------------------------------------------------------
    # Audio format helpers
    # ------------------------------------------------------------------

    def _maybe_convert_audio(self, content, entry, mp, rel_path):
        """Check if a WAV replacement needs format conversion and do it.

        Reads the original encrypted file from the mounted image, decrypts
        it, compares WAV format against the replacement, and converts if
        they differ.  Also matches duration to the original.
        Returns (possibly converted) content bytes.
        """
        import os
        import base64 as _b64
        from .audio import (detect_wav_format, wav_formats_match,
                            format_description, format_diff,
                            needs_ffmpeg, convert_wav_python,
                            is_compressed_wav)
        from .crypto import decrypt_file as _df

        repl_fmt = detect_wav_format(content)
        if repl_fmt is None:
            if is_compressed_wav(content):
                self.log(f"  {rel_path}: compressed WAV — "
                         "attempting ffmpeg conversion", "info")
                # Need ffmpeg to decode compressed WAV; read original for target
                orig_fmt = self._get_original_wav_format(entry, mp)
                if orig_fmt:
                    converted = self._convert_wav_ffmpeg(
                        content, orig_fmt, rel_path)
                    if converted is not None:
                        # Match duration after format conversion
                        return self._resize_wav_to_duration(
                            converted, orig_fmt, rel_path)
                self.log(f"  Warning: could not convert compressed WAV",
                         "error")
            return content  # not a WAV we can parse; pass through

        # Read and decrypt the original to get its format
        orig_fmt = self._get_original_wav_format(entry, mp)
        if orig_fmt is None:
            return content  # can't read original; pass through

        if wav_formats_match(repl_fmt, orig_fmt):
            self.log(f"  Audio format OK: {format_description(repl_fmt)}",
                     "info")
            # Format matches but duration might differ — resize if needed
            return self._resize_wav_to_duration(
                content, orig_fmt, rel_path)

        diff = format_diff(repl_fmt, orig_fmt)
        self.log(f"  Audio format mismatch: {diff}", "info")

        # Try pure Python first (handles bit-depth + channel changes)
        if not needs_ffmpeg(repl_fmt, orig_fmt):
            converted = convert_wav_python(content, repl_fmt, orig_fmt)
            if converted is not None:
                self.log(f"  Converted (Python): "
                         f"{format_description(repl_fmt)} -> "
                         f"{format_description(orig_fmt)}", "success")
                if hasattr(self, '_file_tree_cb'):
                    self._file_tree_cb(rel_path,
                        f"Converted {format_description(orig_fmt)}")
                return self._resize_wav_to_duration(
                    converted, orig_fmt, rel_path)

        # Need ffmpeg for sample rate conversion
        converted = self._convert_wav_ffmpeg(content, orig_fmt, rel_path)
        if converted is not None:
            self.log(f"  Converted (ffmpeg): "
                     f"{format_description(repl_fmt)} -> "
                     f"{format_description(orig_fmt)}", "success")
            if hasattr(self, '_file_tree_cb'):
                self._file_tree_cb(rel_path,
                    f"Converted {format_description(orig_fmt)}")
            return self._resize_wav_to_duration(
                converted, orig_fmt, rel_path)

        self.log(f"  Warning: could not convert {rel_path} ({diff}). "
                 "Game may reject this file.", "error")
        return content

    def _get_original_wav_format(self, entry, mp=None):
        """Read the original encrypted file from the image, decrypt it,
        and return its WAV format dict (or None)."""
        from .audio import detect_wav_format
        from .crypto import decrypt_file as _df

        try:
            if hasattr(self, '_wsl_img') and self._wsl_img:
                # debugfs path — read directly from unmounted image
                orig_enc = self._debugfs_dump_file(entry.path, timeout=120)
            else:
                # mounted path fallback
                import base64 as _b64
                orig_path = f"{mp}{entry.path}"
                enc_b64 = self.executor.run(
                    f"base64 '{orig_path}'", timeout=120).strip()
                orig_enc = _b64.b64decode(enc_b64)
            orig_dec = _df(orig_enc, entry.filler_size, entry.path)
            fmt = detect_wav_format(orig_dec)
            if fmt is not None:
                fmt["_orig_size"] = len(orig_dec)
            return fmt
        except Exception:
            return None

    def _ensure_ffmpeg(self):
        """Install ffmpeg in the executor if not already present."""
        if getattr(self, '_ffmpeg_checked', False):
            return self._ffmpeg_available
        self._ffmpeg_checked = True
        try:
            self.executor.run("which ffmpeg", timeout=10)
            self._ffmpeg_available = True
            return True
        except CommandError:
            pass

        self.log("Installing ffmpeg for audio conversion...", "info")
        try:
            from .executor import DockerExecutor
            if isinstance(self.executor, DockerExecutor):
                self.executor.run(
                    "apk add --no-cache ffmpeg 2>&1", timeout=120)
            else:
                self.executor.run(
                    "DEBIAN_FRONTEND=noninteractive "
                    "apt-get install -y ffmpeg 2>&1", timeout=120)
            self._ffmpeg_available = True
            self.log("ffmpeg installed.", "success")
            return True
        except CommandError as e:
            self._ffmpeg_available = False
            self.log(f"Warning: could not install ffmpeg: {e.output}",
                     "error")
            return False

    def _convert_wav_ffmpeg(self, src_bytes, tgt_fmt, rel_path):
        """Convert audio bytes to target WAV format using ffmpeg.

        Returns converted WAV bytes, or None on failure.
        """
        import os
        import tempfile
        import base64 as _b64
        from .audio import detect_wav_format

        if not self._ensure_ffmpeg():
            self.log("  ffmpeg not available — cannot resample", "error")
            return None

        tmp_dir = self.executor.host_tmp_dir()
        src_tmp = None
        out_tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix='.wav', dir=tmp_dir, delete=False
            ) as tf:
                tf.write(src_bytes)
                src_tmp = tf.name
            out_tmp = src_tmp + '.converted.wav'

            src_exec = self.executor.to_exec_path(src_tmp)
            out_exec = self.executor.to_exec_path(out_tmp)

            codec = f"pcm_s{tgt_fmt['sampwidth'] * 8}le"
            cmd = (
                f"ffmpeg -y -i '{src_exec}' "
                f"-ar {tgt_fmt['framerate']} "
                f"-ac {tgt_fmt['nchannels']} "
                f"-c:a {codec} "
                f"'{out_exec}' 2>&1"
            )
            self.executor.run(cmd, timeout=120)

            # Read the result back
            from .executor import DockerExecutor
            if isinstance(self.executor, DockerExecutor):
                enc = self.executor.run(
                    f"base64 '{out_exec}'", timeout=120).strip()
                return _b64.b64decode(enc)
            else:
                # WSL — the output file is accessible from Windows
                if os.path.isfile(out_tmp) and os.path.getsize(out_tmp) > 44:
                    with open(out_tmp, 'rb') as f:
                        return f.read()
                # Fallback: read via executor
                enc = self.executor.run(
                    f"base64 '{out_exec}'", timeout=120).strip()
                return _b64.b64decode(enc)
        except Exception as e:
            self.log(f"  ffmpeg conversion failed: {e}", "error")
            return None
        finally:
            for p in (src_tmp, out_tmp):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    def _resize_wav_to_duration(self, content, orig_fmt, rel_path):
        """Trim or pad WAV to match the original's exact frame count.

        Pure Python implementation — no ffmpeg needed. Truncates extra
        frames or pads with silence to match orig_fmt["nframes"].
        Returns resized WAV bytes, or original content on failure.
        Skipped when skip_duration_match is True, or when this slot is in
        keep_full_length_paths (a per-slot exemption the user ticked).
        """
        if getattr(self, 'skip_duration_match', False):
            self.log(f"  Duration matching skipped (keep original length)",
                     "info")
            return content
        if rel_path in getattr(self, 'keep_full_length_paths', frozenset()):
            self.log(f"  {rel_path}: keeping full length (per-slot override) — "
                     "not trimming to the original slot length", "info")
            return content

        import io as _io
        import wave
        from .audio import detect_wav_format

        repl_fmt = detect_wav_format(content)
        if repl_fmt is None:
            return content

        target_nframes = orig_fmt["nframes"]
        repl_nframes = repl_fmt["nframes"]
        if repl_nframes == target_nframes:
            return content

        try:
            with wave.open(_io.BytesIO(content), "rb") as w:
                raw_frames = w.readframes(w.getnframes())

            nch = orig_fmt["nchannels"]
            sw = orig_fmt["sampwidth"]
            target_bytes = target_nframes * nch * sw

            if len(raw_frames) > target_bytes:
                raw_frames = raw_frames[:target_bytes]
            elif len(raw_frames) < target_bytes:
                raw_frames = raw_frames + b'\x00' * (
                    target_bytes - len(raw_frames))

            out = _io.BytesIO()
            with wave.open(out, "wb") as w:
                w.setnchannels(nch)
                w.setsampwidth(sw)
                w.setframerate(orig_fmt["framerate"])
                w.writeframes(raw_frames)
            result = out.getvalue()

            orig_dur = target_nframes / orig_fmt["framerate"]
            repl_dur = repl_nframes / repl_fmt["framerate"]
            action = "Trimmed" if repl_nframes > target_nframes else "Padded"
            status = f"{action} {repl_dur:.1f}s -> {orig_dur:.1f}s"
            self.log(
                f"  Duration {action.lower()}: {repl_dur:.2f}s -> "
                f"{orig_dur:.2f}s "
                f"({len(content)} -> {len(result)} bytes)", "success")
            if hasattr(self, '_file_tree_cb'):
                self._file_tree_cb(rel_path, status)
            return result
        except Exception as e:
            self.log(f"  WAV resize failed: {e}", "error")
            return content

    # ------------------------------------------------------------------
    # OGG format helpers
    # ------------------------------------------------------------------

    def _maybe_convert_ogg(self, content, entry, mp, rel_path):
        """Check if an OGG replacement needs format conversion and do it.

        Reads the original encrypted file from the mounted image, decrypts
        it, compares OGG Vorbis format against the replacement, and converts
        via ffmpeg if they differ.  Also matches duration to the original.
        Returns (possibly converted) content bytes.
        """
        from .audio import (detect_ogg_format, ogg_formats_match,
                            ogg_format_description, ogg_format_diff)

        # Sanity-check magic bytes
        if len(content) < 4 or content[:4] != b"OggS":
            self.log(f"  Warning: {rel_path} does not have OGG magic bytes",
                     "error")
            return content

        repl_fmt = detect_ogg_format(content)
        if repl_fmt is None:
            self.log(f"  Warning: could not parse OGG Vorbis header in "
                     f"{rel_path}", "error")
            return content

        orig_fmt = self._get_original_ogg_format(entry, mp)
        if orig_fmt is None:
            self.log(f"  Could not read original OGG format; passing through",
                     "info")
            return content

        orig_dec_bytes = orig_fmt.pop("_orig_bytes", None)

        if ogg_formats_match(repl_fmt, orig_fmt):
            self.log(f"  OGG format OK: {ogg_format_description(repl_fmt)}",
                     "info")
            # Format matches but duration might differ — resize if needed
            if orig_dec_bytes is not None:
                content = self._resize_ogg_to_duration(
                    content, orig_fmt, orig_dec_bytes, rel_path)
            return content

        diff = ogg_format_diff(repl_fmt, orig_fmt)
        self.log(f"  OGG format mismatch: {diff}", "info")

        converted = self._convert_ogg_ffmpeg(content, orig_fmt, rel_path)
        if converted is not None:
            self.log(f"  Converted (ffmpeg): "
                     f"{ogg_format_description(repl_fmt)} -> "
                     f"{ogg_format_description(orig_fmt)}", "success")
            if hasattr(self, '_file_tree_cb'):
                self._file_tree_cb(rel_path,
                    f"Converted {ogg_format_description(orig_fmt)}")
            if orig_dec_bytes is not None:
                converted = self._resize_ogg_to_duration(
                    converted, orig_fmt, orig_dec_bytes, rel_path)
            return converted

        self.log(f"  Warning: could not convert {rel_path} ({diff}). "
                 "Game may ignore this file.", "error")
        return content

    def _get_original_ogg_format(self, entry, mp=None):
        """Read the original encrypted OGG from the image, decrypt it,
        and return its Vorbis format dict (or None)."""
        from .audio import detect_ogg_format
        from .crypto import decrypt_file as _df

        try:
            if hasattr(self, '_wsl_img') and self._wsl_img:
                orig_enc = self._debugfs_dump_file(entry.path, timeout=120)
            else:
                import base64 as _b64
                orig_path = f"{mp}{entry.path}"
                enc_b64 = self.executor.run(
                    f"base64 '{orig_path}'", timeout=120).strip()
                orig_enc = _b64.b64decode(enc_b64)
            orig_dec = _df(orig_enc, entry.filler_size, entry.path)
            fmt = detect_ogg_format(orig_dec)
            if fmt is not None:
                fmt["_orig_size"] = len(orig_dec)
                fmt["_orig_bytes"] = orig_dec
            return fmt
        except Exception:
            return None

    def _convert_ogg_ffmpeg(self, src_bytes, tgt_fmt, rel_path):
        """Convert audio bytes to target OGG Vorbis format using ffmpeg.

        Returns converted OGG bytes, or None on failure.
        """
        import os
        import tempfile
        import base64 as _b64

        if not self._ensure_ffmpeg():
            self.log("  ffmpeg not available — cannot convert OGG", "error")
            return None

        tmp_dir = self.executor.host_tmp_dir()
        src_tmp = None
        out_tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix='.ogg', dir=tmp_dir, delete=False
            ) as tf:
                tf.write(src_bytes)
                src_tmp = tf.name
            out_tmp = src_tmp + '.converted.ogg'

            src_exec = self.executor.to_exec_path(src_tmp)
            out_exec = self.executor.to_exec_path(out_tmp)

            # Target the original's nominal bitrate (or default 112k)
            bitrate = tgt_fmt.get("nominal_bitrate", 112000)
            if bitrate <= 0:
                bitrate = 112000

            cmd = (
                f"ffmpeg -y -i '{src_exec}' "
                f"-ar {tgt_fmt['sample_rate']} "
                f"-ac {tgt_fmt['nchannels']} "
                f"-c:a libvorbis -b:a {bitrate} "
                f"'{out_exec}' 2>&1"
            )
            self.executor.run(cmd, timeout=120)

            # Read the result back
            from .executor import DockerExecutor
            if isinstance(self.executor, DockerExecutor):
                enc = self.executor.run(
                    f"base64 '{out_exec}'", timeout=120).strip()
                return _b64.b64decode(enc)
            else:
                if os.path.isfile(out_tmp) and os.path.getsize(out_tmp) > 28:
                    with open(out_tmp, 'rb') as f:
                        return f.read()
                enc = self.executor.run(
                    f"base64 '{out_exec}'", timeout=120).strip()
                return _b64.b64decode(enc)
        except Exception as e:
            self.log(f"  ffmpeg OGG conversion failed: {e}", "error")
            return None
        finally:
            for p in (src_tmp, out_tmp):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    def _resize_ogg_to_duration(self, content, orig_fmt, orig_dec_bytes,
                                rel_path):
        """Trim or pad OGG to match the original's duration using ffmpeg.

        Uses ffprobe to get durations, then ffmpeg to trim or pad.
        Returns resized OGG bytes, or original content on failure.
        Skipped when skip_duration_match is True, or when this slot is in
        keep_full_length_paths (a per-slot exemption the user ticked).
        """
        if getattr(self, 'skip_duration_match', False):
            self.log(f"  Duration matching skipped (keep original length)",
                     "info")
            return content
        if rel_path in getattr(self, 'keep_full_length_paths', frozenset()):
            self.log(f"  {rel_path}: keeping full length (per-slot override) — "
                     "not trimming to the original slot length", "info")
            return content

        import os
        import tempfile
        import base64 as _b64

        if not self._ensure_ffmpeg():
            return content

        tmp_dir = self.executor.host_tmp_dir()
        src_tmp = None
        orig_tmp = None
        out_tmp = None
        try:
            # Write replacement OGG to temp file
            with tempfile.NamedTemporaryFile(
                suffix='.ogg', dir=tmp_dir, delete=False
            ) as tf:
                tf.write(content)
                src_tmp = tf.name

            # Write original OGG to temp file for duration probing
            with tempfile.NamedTemporaryFile(
                suffix='.ogg', dir=tmp_dir, delete=False
            ) as tf:
                tf.write(orig_dec_bytes)
                orig_tmp = tf.name

            out_tmp = src_tmp + '.resized.ogg'

            src_exec = self.executor.to_exec_path(src_tmp)
            orig_exec = self.executor.to_exec_path(orig_tmp)
            out_exec = self.executor.to_exec_path(out_tmp)

            # Get original duration via ffprobe
            dur_out = self.executor.run(
                f"ffprobe -v error -show_entries format=duration "
                f"-of csv=p=0 '{orig_exec}'", timeout=30).strip()
            orig_dur = float(dur_out)

            # Get replacement duration
            repl_dur_out = self.executor.run(
                f"ffprobe -v error -show_entries format=duration "
                f"-of csv=p=0 '{src_exec}'", timeout=30).strip()
            repl_dur = float(repl_dur_out)

            if abs(repl_dur - orig_dur) < 0.01:
                self.log(f"  OGG duration OK: {repl_dur:.2f}s", "info")
                return content

            bitrate = orig_fmt.get("nominal_bitrate", 112000)
            if bitrate <= 0:
                bitrate = 112000

            if repl_dur > orig_dur:
                # Trim to original duration
                cmd = (
                    f"ffmpeg -y -i '{src_exec}' "
                    f"-t {orig_dur:.6f} "
                    f"-ar {orig_fmt['sample_rate']} "
                    f"-ac {orig_fmt['nchannels']} "
                    f"-c:a libvorbis -b:a {bitrate} "
                    f"'{out_exec}' 2>&1"
                )
            else:
                # Pad with silence to original duration
                cmd = (
                    f"ffmpeg -y -i '{src_exec}' "
                    f"-af 'apad=whole_dur={orig_dur:.6f}' "
                    f"-t {orig_dur:.6f} "
                    f"-ar {orig_fmt['sample_rate']} "
                    f"-ac {orig_fmt['nchannels']} "
                    f"-c:a libvorbis -b:a {bitrate} "
                    f"'{out_exec}' 2>&1"
                )
            self.executor.run(cmd, timeout=120)

            # Read result back
            from .executor import DockerExecutor
            if isinstance(self.executor, DockerExecutor):
                enc = self.executor.run(
                    f"base64 '{out_exec}'", timeout=120).strip()
                result = _b64.b64decode(enc)
            else:
                if os.path.isfile(out_tmp) and os.path.getsize(out_tmp) > 28:
                    with open(out_tmp, 'rb') as f:
                        result = f.read()
                else:
                    enc = self.executor.run(
                        f"base64 '{out_exec}'", timeout=120).strip()
                    result = _b64.b64decode(enc)

            action = "Trimmed" if repl_dur > orig_dur else "Padded"
            status = f"{action} {repl_dur:.1f}s -> {orig_dur:.1f}s"
            self.log(
                f"  OGG duration {action.lower()}: {repl_dur:.2f}s -> "
                f"{orig_dur:.2f}s "
                f"({len(content)} -> {len(result)} bytes)", "success")
            if hasattr(self, '_file_tree_cb'):
                self._file_tree_cb(rel_path, status)

            if len(result) != len(content):
                self.log(
                    f"  Note: OGG byte size changed ({len(result)} vs "
                    f"original {orig_fmt.get('_orig_size', '?')})", "info")

            return result
        except Exception as e:
            self.log(f"  OGG resize failed: {e}", "error")
            return content
        finally:
            for p in (src_tmp, orig_tmp, out_tmp):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    def _phase_encrypt_standalone(self):
        """Re-encrypt changed files using pure Python crypto.

        Writes encrypted files into the raw ext4 image via debugfs
        (no mount needed).  System files (from system/ subfolder) are
        written directly without encryption.
        """
        import os
        import re as _re
        from .crypto import encrypt_file
        from .filelist import parse_fl_dat, detect_edata_prefix

        # Signal to cleanup that the SSD was touched and the post-run
        # e2fsck pass is needed (journal replay).  Read-only Extract
        # runs never reach this phase and so leave the flag False.
        self._wrote_to_ssd = True

        # Separate system files from edata files
        system_files = [(r, p) for r, p in self.changed_files
                        if r.startswith("system/")]
        edata_files = [(r, p) for r, p in self.changed_files
                       if not r.startswith("system/")]

        # Process system files first (plain copy, no encryption)
        if system_files:
            self._write_system_files_debugfs(system_files)

        if not edata_files:
            if system_files:
                self.log("Only system files were modified (no encryption needed).",
                         "success")
            return

        if not self.fl_dat_path:
            raise PipelineError("Encrypt",
                f"Found {len(edata_files)} modified asset file(s) that need "
                f"encryption, but no fl_decrypted.dat is available.\n\n"
                f"Decrypt with Graphics/Sounds checked first to generate "
                f"the file list, then try again.")

        self.log("Loading file list...", "info")
        entries = parse_fl_dat(self.fl_dat_path)
        edata_prefix = detect_edata_prefix(entries)

        # Build lookup
        entry_map = {e.path: e for e in entries}
        self.log(f"Loaded {len(entries)} fl.dat entries.", "info")

        total = len(edata_files)
        ok = 0
        fail = 0

        self.on_progress(0, total, "Encrypting...")
        self.log(f"TOTAL_FILES={total}", "info")

        for i, (rel_path, win_path) in enumerate(edata_files):
            self._check_cancel()

            # Find fl.dat entry
            full_path = f"{edata_prefix}{rel_path}"
            entry = entry_map.get(full_path)
            if not entry:
                self.log(f"[FAIL] {rel_path} (not found in fl.dat)", "error")
                fail += 1
                continue

            # Read replacement content
            with open(win_path, 'rb') as f:
                content = f.read()

            # Auto-convert audio files if format/duration doesn't match
            lower = rel_path.lower()
            if lower.endswith(".wav"):
                content = self._maybe_convert_audio(
                    content, entry, None, rel_path)
            elif lower.endswith(".ogg"):
                content = self._maybe_convert_ogg(
                    content, entry, None, rel_path)

            # Warn if file size differs from original (any file type)
            try:
                orig_stat = self._debugfs_run(
                    f'stat "{entry.path}"', timeout=15)
                m = _re.search(r'Size:\s*(\d+)', orig_stat)
                if m:
                    orig_enc_size = int(m.group(1))
                    orig_content_size = orig_enc_size - entry.filler_size - 4
                    if orig_content_size > 0 and len(content) != orig_content_size:
                        diff = len(content) - orig_content_size
                        direction = "larger" if diff > 0 else "smaller"
                        self.log(
                            f"  Size: {len(content)} bytes "
                            f"({abs(diff)} bytes {direction} than "
                            f"original {orig_content_size})", "info")
            except Exception:
                pass  # non-critical — don't fail on size check

            self.log(f"Processing: {full_path}", "info")
            self.log(f"  filler={entry.filler_size} "
                     f"orig_n2={entry.crc_encrypted} "
                     f"orig_n3={entry.crc_decrypted}", "info")

            # Encrypt with CRC forgery
            try:
                encrypted = encrypt_file(
                    content, entry.filler_size, entry.path,
                    entry.crc_encrypted, entry.crc_decrypted)
            except Exception as e:
                self.log(f"[FAIL] {rel_path}: {e}", "error")
                fail += 1
                continue

            # Verify CRCs
            from .crypto import crc32_buf, decrypt_file as _df
            n2 = crc32_buf(encrypted)
            re_dec = _df(encrypted, entry.filler_size, entry.path)
            n3 = crc32_buf(re_dec)
            n2_ok = n2 == entry.crc_encrypted
            n3_ok = n3 == entry.crc_decrypted

            self.log(f"  n2 forge: want={entry.crc_encrypted} "
                     f"got={n2} {'OK' if n2_ok else 'FAIL'}", "info")
            self.log(f"  n3 forge: want={entry.crc_decrypted} "
                     f"got={n3} {'OK' if n3_ok else 'FAIL'}", "info")

            if not (n2_ok and n3_ok):
                self.log(f"[VERIFY FAIL] {rel_path}", "error")
                fail += 1
                continue

            # Stage encrypted file, then write into image via debugfs
            import hashlib as _hl
            staging = f"{self._debugfs_tmp}/enc_{i:05d}.bin"
            expected_size = len(encrypted)
            _step = "init"
            try:
                native = getattr(self, '_native_debugfs_path', None)
                if native:
                    # Native mode: write binary directly to local temp file
                    _step = f"write binary to {staging}"
                    with open(staging, "wb") as sf:
                        sf.write(encrypted)
                    actual_size = os.path.getsize(staging)
                else:
                    # Docker/WSL mode: stage via base64
                    import base64 as _b64
                    enc_b64 = _b64.b64encode(encrypted).decode()
                    if len(enc_b64) > 30000:
                        _tmp_dir = self.executor.host_tmp_dir()
                        _step = f"tempfile in {_tmp_dir}"
                        with tempfile.NamedTemporaryFile(
                            mode='w', suffix='.b64', delete=False,
                            dir=_tmp_dir,
                        ) as tf:
                            tf.write(enc_b64)
                            tmp_win = tf.name
                        wsl_tmp = self.executor.to_exec_path(tmp_win)
                        _step = f"base64 decode {tmp_win} -> {staging}"
                        try:
                            self.executor.run(
                                f"base64 -d '{wsl_tmp}' > '{staging}'",
                                timeout=60)
                        finally:
                            os.unlink(tmp_win)
                    else:
                        _step = (f"echo base64 ({len(enc_b64)} chars) "
                                 f"-> {staging}")
                        self.executor.run(
                            f"echo '{enc_b64}' | base64 -d > '{staging}'",
                            timeout=30)

                    # Verify staging file size
                    _step = f"stat {staging}"
                    actual_size = int(self.executor.run(
                        f"stat -c%s '{staging}'", timeout=5).strip())

                if actual_size != expected_size:
                    self.log(
                        f"[FAIL] {rel_path} (staging size mismatch: "
                        f"expected {expected_size}, got {actual_size})",
                        "error")
                    fail += 1
                    continue

                # Remove old file from image, write new one via debugfs
                _step = f"debugfs rm {entry.path}"
                self._debugfs_run(
                    f'rm "{entry.path}"', writable=True, timeout=30)
                _step = f"debugfs write {staging} -> {entry.path}"
                self._debugfs_run(
                    f'write "{staging}" "{entry.path}"',
                    writable=True, timeout=120)

                # Verify file was written by checking size via debugfs stat
                _step = f"debugfs stat {entry.path}"
                stat_out = self._debugfs_run(
                    f'stat "{entry.path}"', timeout=15)
                m = _re.search(r'Size:\s*(\d+)', stat_out)
                if m:
                    disk_size = int(m.group(1))
                    if disk_size != expected_size:
                        self.log(
                            f"[FAIL] {rel_path} (debugfs size mismatch: "
                            f"expected {expected_size}, got {disk_size})",
                            "error")
                        fail += 1
                        continue

                self.log(f"[VERIFY OK] {rel_path}", "success")
                if hasattr(self, '_file_tree_cb'):
                    self._file_tree_cb(rel_path, "Encrypted OK")
                ok += 1
                # Save expected MD5 + size for the post-write spot-check
                if not hasattr(self, '_expected_spot'):
                    self._expected_spot = {
                        'md5': _hl.md5(encrypted).hexdigest(),
                        'size': len(encrypted),
                        'content_md5': _hl.md5(content).hexdigest(),
                    }
            except (CommandError, OSError) as e:
                self.log(f"[FAIL] {rel_path} (write failed at step "
                         f"'{_step}': {e})", "error")
                fail += 1

            self.on_progress(i + 1, total, f"ok={ok} fail={fail}")

        self.on_progress(total, total, "Complete")
        summary = f"{ok}/{total} files replaced and verified"
        if fail > 0:
            summary += f" ({fail} FAILED)"
            self.log(summary, "error")
        else:
            summary += " successfully"
            self.log(summary, "success")

        if edata_files:
            self.log("CRC32 forgery: encrypted files match original fl.dat checksums.",
                     "success")

    def _write_system_files_debugfs(self, system_files):
        """Write modified system files directly into the ext4 image via debugfs.

        These files are NOT encrypted — they live outside edata/ on the
        filesystem and are not listed in fl.dat, so no CRC forgery is needed.
        """
        import os
        import base64 as _b64

        total = len(system_files)
        self.log(f"Writing {total} system file(s) (no encryption)...", "info")
        self.on_progress(0, total, "Writing system files...")
        ok = 0
        fail = 0

        for i, (rel_path, win_path) in enumerate(system_files):
            self._check_cancel()

            # Convert system/jjpe/gen1/Game/file -> /jjpe/gen1/Game/file
            fs_path = "/" + rel_path[len("system/"):]

            with open(win_path, 'rb') as f:
                content = f.read()

            self.log(f"  System file: {fs_path} ({len(content)} bytes)", "info")

            # Stage file, then write via debugfs
            staging = f"{self._debugfs_tmp}/sys_{i:05d}.bin"
            try:
                native = getattr(self, '_native_debugfs_path', None)
                if native:
                    with open(staging, "wb") as sf:
                        sf.write(content)
                else:
                    enc_b64 = _b64.b64encode(content).decode()
                    if len(enc_b64) > 30000:
                        with tempfile.NamedTemporaryFile(
                            mode='w', suffix='.b64', delete=False,
                            dir=self.executor.host_tmp_dir(),
                        ) as tf:
                            tf.write(enc_b64)
                            tmp_win = tf.name
                        wsl_tmp = self.executor.to_exec_path(tmp_win)
                        try:
                            self.executor.run(
                                f"base64 -d '{wsl_tmp}' > '{staging}'",
                                timeout=60)
                        finally:
                            os.unlink(tmp_win)
                    else:
                        self.executor.run(
                            f"echo '{enc_b64}' | base64 -d > '{staging}'",
                            timeout=30)

                # Write into image via debugfs
                self._debugfs_run(
                    f'rm "{fs_path}"', writable=True, timeout=30)
                self._debugfs_run(
                    f'write "{staging}" "{fs_path}"',
                    writable=True, timeout=120)

                self.log(f"  [OK] {fs_path}", "success")
                ok += 1
            except (CommandError, OSError) as e:
                self.log(f"  [FAIL] {fs_path}: {e}", "error")
                fail += 1

            self.on_progress(i + 1, total, f"ok={ok} fail={fail}")

        self.on_progress(total, total, "System files complete")
        self.log(f"System files: {ok}/{total} written"
                 f"{f' ({fail} failed)' if fail else ''}",
                 "success" if fail == 0 else "error")

    def _verify_raw_image(self, wsl_img):
        """Spot-check modifications via debugfs dump (no mount needed).

        Reads the first changed file back from the image, compares MD5/size
        against expected values, then decrypts and compares content against
        the replacement file.

        Raises PipelineError if verification fails — the ISO would be broken.
        """
        # Pick the first changed edata file for a quick spot-check
        edata_changed = [(r, p) for r, p in self.changed_files
                         if not r.startswith("system/")]
        if not edata_changed:
            self.log("Only system files modified — skipping encrypted "
                     "file verification.", "info")
            return
        rel_path, win_path = edata_changed[0]
        from .filelist import parse_fl_dat, detect_edata_prefix
        entries = parse_fl_dat(self.fl_dat_path)
        edata_prefix = detect_edata_prefix(entries)
        entry_map = {e.path: e for e in entries}
        full_path = f"{edata_prefix}{rel_path}"
        entry = entry_map.get(full_path)

        expected = getattr(self, '_expected_spot', None)
        verification_failed = False

        self.log("Verifying modifications in raw image (debugfs)...", "info")
        try:
            disk_encrypted = self._debugfs_dump_file(full_path, timeout=120)
            import hashlib as _hl
            raw_md5 = _hl.md5(disk_encrypted).hexdigest()
            raw_size = len(disk_encrypted)

            # Compare against what the encrypt phase wrote
            if expected:
                md5_match = raw_md5 == expected['md5']
                size_match = raw_size == expected['size']
                if md5_match and size_match:
                    self.log(
                        f"  Encrypted bytes match expected "
                        f"(md5={raw_md5[:12]}..., size={raw_size})",
                        "success")
                else:
                    verification_failed = True
                    self.log(
                        f"  FAILED: Encrypted bytes do NOT match!",
                        "error")
                    self.log(
                        f"    Expected: md5={expected['md5'][:12]}... "
                        f"size={expected['size']}",
                        "error")
                    self.log(
                        f"    On disk:  md5={raw_md5[:12]}... size={raw_size}",
                        "error")

            # Decrypt and compare content against what the encrypt phase wrote.
            # We use expected['content_md5'] (saved after audio resizing) rather
            # than re-reading win_path, because the encrypt phase may have
            # trimmed/padded audio to match original duration.
            if entry and not verification_failed:
                from .crypto import decrypt_file as _df
                disk_decrypted = _df(
                    disk_encrypted, entry.filler_size, entry.path)
                # Strip the 4-byte CRC forgery suffix to get original content
                disk_content = (disk_decrypted[:-4]
                                if len(disk_decrypted) > 4
                                else disk_decrypted)
                disk_content_md5 = _hl.md5(disk_content).hexdigest()

                if expected and 'content_md5' in expected:
                    expected_content_md5 = expected['content_md5']
                else:
                    # Fallback: read the file from disk (pre-audio-resize)
                    with open(win_path, 'rb') as fh:
                        expected_content_md5 = _hl.md5(fh.read()).hexdigest()

                if disk_content_md5 == expected_content_md5:
                    self.log(
                        f"  Content round-trip verified: {rel_path} "
                        f"(md5={disk_content_md5[:12]}...)",
                        "success")
                else:
                    verification_failed = True
                    self.log(
                        f"  FAILED: Decrypted content does NOT match "
                        f"replacement file!",
                        "error")
                    self.log(
                        f"    Expected: md5={expected_content_md5[:12]}...",
                        "error")
                    self.log(
                        f"    On disk:  md5={disk_content_md5[:12]}...",
                        "error")

        except Exception as e:
            self.log(f"  Raw image spot-check skipped: {e}", "info")

        if verification_failed:
            raise PipelineError(
                "Verification",
                "Modified files did not persist to the raw image.\n\n"
                "debugfs write may have failed. The ISO was NOT built.\n\n"
                "Please check the log for errors and try again."
            )

    def _phase_convert_standalone(self):
        """Verify, repair, and convert the modified raw image.

        No unmount needed — debugfs wrote directly to the image file.
        """
        wsl_img = self._wsl_img

        # Verify modifications via debugfs dump
        if self.changed_files:
            self.on_progress(0, 100, "Verifying raw image...")
            self._verify_raw_image(wsl_img)

        self.log("Running e2fsck...", "info")
        try:
            for line in self.executor.stream(
                f"e2fsck -fy '{wsl_img}' 2>&1", timeout=300
            ):
                clean = line.strip()
                if clean:
                    self.log(f"  {clean}", "info")
        except CommandError:
            pass

        self._ensure_iso_tools()

        # Re-mount if the previous mount was cleaned up by systemd-tmpfiles-clean
        if self._iso_mount:
            try:
                self.executor.run(
                    f"mountpoint -q '{self._iso_mount}'", timeout=5)
            except CommandError:
                self.log("ISO mount disappeared, re-mounting...", "info")
                self._iso_mount = None

        if not self._iso_mount:
            wsl_iso = self.executor.to_exec_path(self.image_path)
            import uuid as _uuid
            tag = _uuid.uuid4().hex[:8]
            self._iso_mount = f"/var/tmp/jjp_iso_{tag}"
            try:
                self.executor.run(f"mkdir -p {self._iso_mount}", timeout=10)
                self.executor.run(
                    f"mount -o loop,ro '{wsl_iso}' {self._iso_mount}",
                    timeout=config.MOUNT_TIMEOUT)
            except CommandError as e:
                raise PipelineError("Convert",
                    f"Failed to mount original ISO: {e.output}") from e

        # Rest is same as parent _phase_convert from the partclone step
        partimag = f"{self._iso_mount}{config.PARTIMAG_PATH}"
        part_prefix = f"{partimag}/{config.GAME_PARTITION}.ext4-ptcl-img.gz"
        try:
            parts_out = self.executor.run(
                f"ls -1 {part_prefix}.* 2>/dev/null | sort", timeout=10)
        except CommandError:
            parts_out = ""
        parts = [p.strip() for p in parts_out.strip().split("\n") if p.strip()]
        if not parts:
            raise PipelineError("Convert",
                f"No partclone image for {config.GAME_PARTITION} found in ISO.")

        split_size = "1000000000"
        try:
            sz = self.executor.run(
                f"stat -c%s '{parts[0]}'", timeout=5).strip()
            split_size = sz
        except (CommandError, ValueError):
            pass

        try:
            self.executor.run("which pigz", timeout=5)
            compressor = "pigz -c --fast -b 1024 --rsyncable"
        except CommandError:
            compressor = "gzip -c --fast --rsyncable"

        import uuid as _uuid
        tag = _uuid.uuid4().hex[:8]
        self._chunks_dir = f"/var/tmp/jjp_chunks_{tag}"
        output_prefix = (f"{self._chunks_dir}/"
                         f"{config.GAME_PARTITION}.ext4-ptcl-img.gz.")
        self.executor.run(f"mkdir -p '{self._chunks_dir}'", timeout=10)

        self.log(f"Converting {wsl_img} to partclone format...", "info")
        self.log("This may take 10-30 minutes depending on image size.", "info")

        convert_cmd = (
            f"set -o pipefail && "
            f"partclone.ext4 -c -s '{wsl_img}' -o - "
            f"2> >(stdbuf -oL tr '\\r' '\\n' > /var/tmp/jjp_ptcl.log) "
            f"| {compressor} "
            f"| split -b {split_size} -a 2 - '{output_prefix}'"
        )
        monitor_script = (
            f"#!/bin/bash\n"
            f"({convert_cmd}) &\n"
            f"PID=$!\n"
            f"LAST_PCT=-1\n"
            f"while kill -0 $PID 2>/dev/null; do\n"
            f"  sleep 3\n"
            f"  PCT=$(grep -oP 'Completed:\\s*\\K[\\d.]+' "
            f"/var/tmp/jjp_ptcl.log 2>/dev/null | tail -1)\n"
            f"  OSIZE=$(du -sb '{output_prefix}'* 2>/dev/null "
            f"| awk '{{s+=$1}} END {{printf \"%d\", s}}')\n"
            f"  if [ -n \"$PCT\" ]; then\n"
            f"    CUR=$(printf '%.0f' \"$PCT\" 2>/dev/null || echo 0)\n"
            f"    if [ \"$CUR\" != \"$LAST_PCT\" ]; then\n"
            f"      LAST_PCT=$CUR\n"
            f"      echo \"PROGRESS:${{PCT}}% output=${{OSIZE:-0}}\"\n"
            f"    fi\n"
            f"  else\n"
            f"    echo \"PROGRESS:0% output=${{OSIZE:-0}}\"\n"
            f"  fi\n"
            f"done\n"
            f"wait $PID\n"
            f"exit $?\n"
        )
        import base64
        monitor_path = "/var/tmp/jjp_convert_monitor.sh"
        monitor_b64 = base64.b64encode(monitor_script.encode()).decode()
        self.executor.run(
            f"echo '{monitor_b64}' | base64 -d > {monitor_path} && "
            f"chmod +x {monitor_path}",
            timeout=10)

        self.log("Starting partclone conversion pipeline...", "info")
        last_pct = -1
        try:
            for line in self.executor.stream(
                f"bash {monitor_path}", timeout=config.ISO_CONVERT_TIMEOUT
            ):
                if self.cancelled:
                    self.executor.kill()
                    raise PipelineError("Convert", "Cancelled by user.")
                clean = line.strip()
                if not clean:
                    continue
                m = re.search(r'PROGRESS:([\d.]+)%\s*output=(\d+)', clean)
                if m:
                    pct = float(m.group(1))
                    ipct = int(pct)
                    out_mb = int(m.group(2)) / (1024**2)
                    if ipct > last_pct:
                        last_pct = ipct
                        self.on_progress(ipct, 100,
                            f"{ipct}% ({out_mb:.0f} MB written)")
                        if ipct % 10 == 0:
                            self.log(
                                f"  Conversion: {ipct}% "
                                f"({out_mb:.0f} MB written)", "info")
        except CommandError as e:
            log_content = ""
            try:
                log_content = self.executor.run(
                    "tail -5 /var/tmp/jjp_ptcl.log 2>/dev/null",
                    timeout=5).strip()
            except CommandError:
                pass
            raise PipelineError("Convert",
                f"Partclone conversion failed: {e.output}\n"
                f"{log_content}") from e

        try:
            parts_out = self.executor.run(
                f"ls -lh '{output_prefix}'* 2>/dev/null",
                timeout=10).strip()
            self.log(f"Partclone files created:\n{parts_out}", "success")
        except CommandError:
            raise PipelineError("Convert",
                "No partclone output files were created.")

        # Verify new chunks differ from original chunks
        self.on_progress(100, 100, "Verifying chunks...")
        try:
            new_first = f"{output_prefix}aa"
            orig_first = f"{part_prefix}.aa"
            new_cksum = self.executor.run(
                f"md5sum '{new_first}' | cut -d' ' -f1", timeout=300).strip()
            orig_cksum = self.executor.run(
                f"md5sum '{orig_first}' | cut -d' ' -f1", timeout=300).strip()
            if new_cksum == orig_cksum:
                self.log(
                    "WARNING: New partition chunks are IDENTICAL to originals! "
                    "Changes may not have persisted to the raw ext4 image.",
                    "error")
            else:
                self.log(
                    f"Chunk verification: new differs from original "
                    f"(orig={orig_cksum[:8]}… new={new_cksum[:8]}…)",
                    "success")
        except Exception as e:
            self.log(f"Chunk verification skipped: {e}", "info")

        self.on_progress(100, 100, "Conversion complete")

    def _phase_cleanup_standalone(self):
        """Simplified cleanup - no daemon or USB."""
        self.log("Cleaning up...", "info")

        # mount_point is None when using debugfs (no mount to undo)
        if self.mount_point:
            try:
                self.executor.run(
                    f"umount -l '{self.mount_point}' 2>/dev/null; true",
                    timeout=30)
            except CommandError:
                pass
            try:
                self.executor.run(
                    f"rmdir '{self.mount_point}' 2>/dev/null; true",
                    timeout=5)
            except CommandError:
                pass

        # Clean up debugfs staging directory
        if hasattr(self, '_debugfs_tmp') and self._debugfs_tmp:
            try:
                self.executor.run(
                    f"rm -rf '{self._debugfs_tmp}'", timeout=60)
            except CommandError:
                pass

        if self._iso_mount:
            try:
                self.executor.run(
                    f"umount -l '{self._iso_mount}' 2>/dev/null; true",
                    timeout=15)
                self.executor.run(
                    f"rmdir '{self._iso_mount}' 2>/dev/null; true",
                    timeout=5)
            except CommandError:
                pass

        if hasattr(self, '_chunks_dir') and self._chunks_dir:
            try:
                self.executor.run(
                    f"rm -rf '{self._chunks_dir}'", timeout=60)
            except CommandError:
                pass

        try:
            self.executor.run(
                "rm -f /var/tmp/jjp_ptcl.log /var/tmp/jjp_convert_monitor.sh "
                "/var/tmp/jjp_build_iso.sh 2>/dev/null; true", timeout=5)
        except CommandError:
            pass

        # Stop Docker container if applicable
        from .executor import DockerExecutor
        if isinstance(self.executor, DockerExecutor):
            try:
                self.executor.stop_container()
            except Exception:
                pass

        self.log("Cleanup complete.", "success")


# ==================================================================
# Direct SSD pipelines — modify files on a physically-connected SSD
# ==================================================================

# Normalise per-OS partition-type labels into a small, finite set so the
# pick-the-game-partition code doesn't have to care which platform it's
# running on.  Anything we don't recognise is "unknown" (still a valid
# candidate — Windows reports ext4 as "Unknown" since it has no driver,
# which is the whole reason we can't just trust the type label).
_WIN_TYPE_TO_FS_KIND = {
    "ifs":           "ntfs",     # Windows NTFS / installable FS marker
    "basic":         "unknown",  # generic data — could be anything
    "system":        "efi",      # EFI System Partition
    "reserved":      "msr",      # MS Reserved
    "recovery":      "recovery",
    "unknown":       "linux",    # no Windows driver → most often ext4
}

_MAC_TYPE_TO_FS_KIND = {
    "linux filesystem":     "linux",
    "linux swap":           "swap",
    "efi":                  "efi",
    "microsoft basic data": "unknown",
    "ms reserved":          "msr",
    "apple_hfs":            "hfs",
    "apple_apfs":           "apfs",
}


@dataclass
class _PartitionInfo:
    """One entry in the partition map for a JJP SSD.

    Built by ``_discover_partitions`` on every Direct-SSD run so the
    full layout is always in the log file regardless of whether the
    auto-pick succeeds.  ``raw_type`` keeps the OS-native label
    verbatim — diagnostics — while ``fs_kind`` is the normalised
    category the pick logic actually reads.

    Mount-probe fields (``has_jjpe_gen1``, ``jjpe_mtime``,
    ``boot_listing``) are filled in by the content-verify loop in
    ``_mount_ssd``; they stay at their defaults if that partition
    was never mounted.
    """
    number: int                    # 1-indexed partition number
    raw_type: str                  # OS-native type string, for the log
    size_bytes: int                # 0 if unknown
    fs_kind: str = "unknown"       # linux | efi | fat | ntfs | swap | …
    has_jjpe_gen1: bool = False    # set True once content-verify finds it
    jjpe_mtime: int = 0            # epoch seconds — newer = more recent activity
    boot_listing: list = field(default_factory=list)  # top-level names on small FAT/EFI


# ----------------------------------------------------------------------
# Per-OS partition-table parsers — module-level so they can be unit
# tested directly against canned PowerShell / diskutil / lsblk output
# without spinning up a real executor.
# ----------------------------------------------------------------------

def _parse_windows_partitions(raw_output):
    """Parse ``num|type|size`` lines from Get-Partition into _PartitionInfo.

    Empty input or junk lines just yield an empty list — the caller
    treats a missing partition map as "fall back to default".
    """
    out_parts = []
    if not raw_output:
        return out_parts
    for line in raw_output.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        fields = line.split("|", 2)
        if len(fields) < 3:
            continue
        try:
            num = int(fields[0].strip())
            size = int(fields[2].strip())
        except ValueError:
            continue
        raw_type = fields[1].strip()
        fs_kind = _WIN_TYPE_TO_FS_KIND.get(raw_type.lower(), "unknown")
        out_parts.append(_PartitionInfo(
            number=num, raw_type=raw_type,
            size_bytes=size, fs_kind=fs_kind))
    return out_parts


def _parse_macos_partitions(raw_output):
    """Parse ``diskutil list <device>`` output into _PartitionInfo.

    Each partition row looks like ``   2:  Linux Filesystem
    12.0 GB   disk2s2``.  We anchor on the trailing ``diskNsM``
    instead of the leading index column because diskutil reflows
    label widths between versions.
    """
    out_parts = []
    if not raw_output:
        return out_parts
    for line in raw_output.splitlines():
        m = re.match(
            r'\s*\d+:\s+(.+?)\s+([\d.]+)\s+(TB|GB|MB|KB|B)\s+'
            r'disk\d+s(\d+)',
            line)
        if not m:
            continue
        raw_type = m.group(1).strip()
        val = float(m.group(2))
        unit = m.group(3)
        size = int(val * {
            'TB': 1e12, 'GB': 1e9, 'MB': 1e6, 'KB': 1e3, 'B': 1,
        }.get(unit, 1))
        num = int(m.group(4))
        fs_kind = _MAC_TYPE_TO_FS_KIND.get(
            raw_type.lower(), "unknown")
        # Fuzzy fallbacks — diskutil's TYPE column often runs the
        # type label and the volume name together (e.g. "EFI EFI",
        # "Linux Filesystem MYDRIVE") which the strict dict misses.
        if fs_kind == "unknown":
            label = raw_type.lower()
            if "linux" in label:
                fs_kind = "linux"
            elif "efi" in label:
                fs_kind = "efi"
            elif "swap" in label:
                fs_kind = "swap"
        out_parts.append(_PartitionInfo(
            number=num, raw_type=raw_type,
            size_bytes=size, fs_kind=fs_kind))
    return out_parts


def _parse_linux_partitions(raw_output):
    """Parse ``lsblk -brno NAME,FSTYPE,SIZE`` output into _PartitionInfo.

    ``-b`` makes the size column an int (bytes) — without it lsblk
    returns "12G" / "500M" and we'd have to undo a localised
    rounding.
    """
    out_parts = []
    if not raw_output:
        return out_parts
    for line in raw_output.strip().splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        name = fields[0]
        fstype = fields[1] if len(fields) >= 3 else ""
        try:
            size = int(fields[-1])
        except ValueError:
            continue
        m = re.search(r'(\d+)$', name)
        if not m:
            continue
        num = int(m.group(1))
        fs_lower = fstype.lower() if fstype else ""
        if fs_lower in ("ext4", "ext3", "ext2"):
            fs_kind = "linux"
        elif fs_lower in ("vfat", "fat32", "fat16", "msdos"):
            fs_kind = "fat"
        elif fs_lower == "ntfs":
            fs_kind = "ntfs"
        elif fs_lower == "swap":
            fs_kind = "swap"
        else:
            fs_kind = fs_lower or "unknown"
        out_parts.append(_PartitionInfo(
            number=num, raw_type=fstype or "(no fstype)",
            size_bytes=size, fs_kind=fs_kind))
    return out_parts


class DirectSSDDecryptPipeline(StandaloneDecryptPipeline):
    """Decrypt files directly from a physically-connected JJP game SSD.

    Skips the ISO extract phase entirely — mounts the SSD's ext4 partition
    directly via WSL (Windows), Docker (macOS), or native mount (Linux).

    Phases: Mount → Decrypt → Cleanup
    """

    def __init__(self, device_path, output_path, fl_dat_path,
                 log_cb, phase_cb, progress_cb, done_cb,
                 full_dump=False, extract_graphics=True,
                 extract_sounds=True, partition_override=None):
        # Pass device_path as image_path (we override mount logic)
        super().__init__(device_path, output_path, fl_dat_path,
                         log_cb, phase_cb, progress_cb, done_cb,
                         full_dump=full_dump,
                         extract_graphics=extract_graphics,
                         extract_sounds=extract_sounds)
        self.device_path = device_path  # e.g. \\.\PHYSICALDRIVE2 or /dev/sdb
        # User-supplied partition number that overrides auto-discovery.
        # The escape hatch for drives whose layout the enumerator misses;
        # set via the GUI's "Force partition #" field.
        self.partition_override = partition_override
        self._ssd_mounted = False
        self._wsl_mount_device = None  # for Windows wsl --unmount
        self._disk_was_offlined = False
        self._ssd_image_path = None    # raw image of SSD partition (macOS)
        self._needs_writeback = False   # write image back to SSD on success
        self._partition_map = []        # filled by _discover_partitions for diagnostics
        self._ab_partitions = None      # filled when an A/B layout is detected
        # Set True the moment a writable debugfs call lands against the
        # SSD.  Gates the cleanup-time e2fsck pass — read-only Extract
        # runs don't need (and on macOS often can't successfully run)
        # the post-mount fsck, and a failure there should not surface
        # as a scary error when the SSD wasn't touched.
        self._wrote_to_ssd = False

    def run(self):
        """Execute the direct SSD decrypt pipeline."""
        from .executor import DockerExecutor
        cleanup_phase = len(config.DIRECT_SSD_PHASES) - 1
        # Keep the host awake for the whole run.  Direct-SSD
        # extractions take ~30 min on a populated JJP image, and
        # macOS users have hit cases where idle-sleep stretched
        # wall-clock to 2+ hours.  The context manager handles all
        # three platforms; on unsupported / missing-helper systems
        # it silently no-ops and the run still proceeds.
        with _PreventSystemSleep(
                reason="Pinball Asset Decryptor SSD extraction"):
            self._run_inner(cleanup_phase)

    def _run_inner(self, cleanup_phase):
        try:
            self._log_system_diagnostics()
            self.log(f"Direct SSD mode — device: {self.device_path}", "info")
            self.log(
                "Sleep prevention active — host will stay awake "
                "for the duration of this run.",
                "info")

            # Verify output path is accessible
            ok, msg = self.executor.check_path_accessible(self.output_path)
            if not ok:
                raise PipelineError("Mount", f"Output folder path error:\n{msg}")

            self.on_phase(0)  # Mount
            self._mount_ssd(read_only=True)
            self._check_cancel()

            native = getattr(self, '_native_debugfs_path', None)
            if native:
                # ── Native debugfs path (macOS, no Docker) ──
                # Game detection already done in _mount_ssd.

                self.on_phase(1)  # Decrypt
                self._phase_decrypt_native()
                self._check_cancel()

                if self.full_dump:
                    self._phase_copy_full_filesystem_native()
                    self._check_cancel()

                self._generate_checksums_native()
            else:
                # ── Docker / WSL path ──
                self._detect_game()

                self.on_phase(1)  # Decrypt
                self._phase_decrypt_standalone()
                self._check_cancel()

                if self.full_dump:
                    self._phase_copy_full_filesystem()
                    self._check_cancel()

                wsl_out = self.executor.to_exec_path(self.output_path)
                self._generate_checksums(wsl_out)

            self._succeeded = True
            self.on_phase(cleanup_phase)  # Cleanup
            self._cleanup_ssd()
            self.on_done(True, f"Decryption complete! Files saved to:\n{self.output_path}")

        except PipelineError as e:
            self.log(str(e), "error")
            self.on_phase(cleanup_phase)
            self._cleanup_ssd()
            self.on_done(False, str(e))
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.on_phase(cleanup_phase)
            self._cleanup_ssd()
            self.on_done(False, f"Unexpected error: {e}")

    def _phase_decrypt_native(self):
        """Decrypt files using native debugfs + Python crypto (no Docker).

        Uses debugfs to dump individual files from the raw SSD partition,
        decrypts them in-process, and writes output directly to the host.
        """
        from .crypto import decrypt_file, detect_filler_size, crc32_buf
        from .filelist import parse_fl_dat, detect_edata_prefix, \
            FileEntry, write_fl_dat

        out_dir = self.output_path
        os.makedirs(out_dir, exist_ok=True)
        game_name = self.game_name or ""
        if not game_name:
            raise PipelineError("Decrypt",
                "Could not detect game name on the SSD. "
                "The partition may not contain a JJP game, or the "
                "filesystem layout is unexpected.")
        edata_dir = f"{config.GAME_BASE_PATH}/{game_name}/edata"

        has_fl_dat = self.fl_dat_path and os.path.isfile(self.fl_dat_path)

        if has_fl_dat:
            entries = parse_fl_dat(self.fl_dat_path)
            prefix = detect_edata_prefix(entries)
            # Copy fl_dat to output
            import shutil
            fl_dest = os.path.join(out_dir, "fl_decrypted.dat")
            if os.path.normpath(os.path.abspath(self.fl_dat_path)) != \
               os.path.normpath(fl_dest):
                shutil.copy2(self.fl_dat_path, fl_dest)
            self.log("Using cached fl_decrypted.dat", "info")
            paths = None  # filler_size already known per-entry
        else:
            # Discover paths only — DO NOT dump-and-scan up front.
            # The old design dumped every file twice (once to detect
            # filler sizes, once to decrypt), making a 5400-file SSD
            # take ~1 hour and report no log progress for the second
            # half.  Fuse path-collection + dump + filler-detect +
            # decrypt + write into one loop below.
            self.log("Scanning edata directory via debugfs...", "info")
            paths = []
            self._debugfs_ls_recursive(edata_dir, paths)
            self.log(f"Found {len(paths)} files in edata.", "info")
            # Prefix is needed for output-path stripping AND the
            # category filter; derive from first discovered path.
            prefix = ""
            for p in paths:
                idx = p.find("/edata/")
                if idx >= 0:
                    prefix = p[:idx + 7]
                    break
            entries = paths  # passed through filter below as paths

        # Filter by category — works on either FileEntry list (fl_dat
        # path) or bare path list (scan path); both expose .path or
        # are themselves the path string.
        def _path_of(item):
            return item if isinstance(item, str) else item.path

        if not self.extract_graphics or not self.extract_sounds:
            def _keep(item):
                p = _path_of(item)
                rel = p[len(prefix):] if prefix and \
                    p.startswith(prefix) else p
                if rel.startswith("graphics/"):
                    return self.extract_graphics
                if rel.startswith("sound/"):
                    return self.extract_sounds
                return True
            before = len(entries)
            entries = [e for e in entries if _keep(e)]
            if before != len(entries):
                self.log(f"Filtered to {len(entries)}/{before} files by "
                         f"category selection", "info")

        total = len(entries)
        if total == 0:
            self.log("No files to decrypt.", "info")
            return

        self.log(f"TOTAL_FILES={total}", "info")
        self.on_progress(0, total, "Decrypting...")

        ok = fail = skip = 0
        computed_entries = []
        tmp_file = os.path.join(tempfile.gettempdir(),
                                f"jjp_dump_{uuid.uuid4().hex[:8]}.bin")

        # Log progress to the text log (not just the progress bar)
        # every 60 s so the user can tell the decrypt phase is
        # alive — the previous design only updated on_progress()
        # which feeds the GUI bar; the log stayed silent for the
        # entire ~30-minute decrypt and looked stuck.
        import time
        last_log_ts = time.monotonic()

        try:
            for i, item in enumerate(entries):
                self._check_cancel()
                path = _path_of(item)
                # filler_size is known when we came from fl_dat;
                # unknown (-1 sentinel) when we discovered via scan
                # and must be detected from the dumped bytes.
                known_filler = (
                    item.filler_size if not isinstance(item, str)
                    else None)

                # Dump file from SSD via debugfs
                try:
                    self._debugfs_run(
                        f'dump "{path}" "{tmp_file}"', timeout=30)
                except CommandError:
                    skip += 1
                    if (i + 1) % 100 == 0 or i + 1 == total:
                        self.on_progress(
                            i + 1, total,
                            f"ok={ok} fail={fail} skip={skip}")
                    continue

                if not os.path.isfile(tmp_file):
                    skip += 1
                    continue

                try:
                    with open(tmp_file, "rb") as f:
                        enc_data = f.read()

                    if len(enc_data) < 8:
                        skip += 1
                        continue

                    if known_filler is not None:
                        filler_size = known_filler
                    else:
                        filler_size = detect_filler_size(enc_data, path)
                        if filler_size < 0:
                            skip += 1
                            continue

                    if len(enc_data) <= filler_size:
                        skip += 1
                        continue

                    content = decrypt_file(enc_data, filler_size, path)
                    rel = path[len(prefix):] if prefix and \
                        path.startswith(prefix) else path
                    out_path = os.path.join(out_dir, rel)
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(content)

                    if not has_fl_dat:
                        n2 = crc32_buf(enc_data)
                        n3 = crc32_buf(content)
                        computed_entries.append(FileEntry(
                            path=path, filler_size=filler_size,
                            crc_encrypted=n2, crc_decrypted=n3))
                    ok += 1
                except Exception as ex:
                    self.log(f"[FAIL] {path}: {ex}", "error")
                    fail += 1
                finally:
                    try:
                        os.unlink(tmp_file)
                    except OSError:
                        pass

                if (i + 1) % 100 == 0 or i + 1 == total:
                    self.on_progress(
                        i + 1, total,
                        f"ok={ok} fail={fail} skip={skip}")

                now = time.monotonic()
                if now - last_log_ts >= 60.0 or i + 1 == total:
                    self.log(
                        f"  Decrypted {i + 1}/{total} "
                        f"(ok={ok} fail={fail} skip={skip})",
                        "info")
                    last_log_ts = now
        finally:
            # Ensure temp file is removed
            try:
                os.unlink(tmp_file)
            except OSError:
                pass

        if not has_fl_dat and computed_entries:
            fl_out = os.path.join(out_dir, "fl_decrypted.dat")
            write_fl_dat(computed_entries, fl_out)
            self.log(f"Generated fl_decrypted.dat with "
                     f"{len(computed_entries)} entries", "info")

        self.on_progress(total, total, "Complete")
        self.log(
            f"Decryption finished: {ok} OK, {fail} failed "
            f"out of {ok + fail + skip} files.",
            "success" if fail == 0 else "info")

        # Same honesty rule as the ISO flow: walking the whole edata tree and
        # writing nothing is a failed run, not a finished one.
        if ok == 0 and total > 0 and (self.extract_graphics
                                      or self.extract_sounds):
            raise PipelineError("Decrypt", self._nothing_decrypted_message(
                total, 0 if skip == total else None))

    def _detect_game_via_debugfs(self):
        """Detect game name on the SSD via debugfs.

        Primary method: stat the edata directory for each known game.
        Fallback: parse ``ls -p`` output for unknown game directories.
        """
        # Fast path: check known game names directly via stat
        # Check for edata dir (always present) and game binary
        for name in config.KNOWN_GAMES:
            for target in ("edata", "game"):
                try:
                    stat_out = self._debugfs_run(
                        f'stat "{config.GAME_BASE_PATH}/{name}/{target}"',
                        timeout=10)
                    self.log(f"debugfs stat {name}/{target}: "
                             f"{stat_out[:200]}", "info")
                    # debugfs returns exit 0 even on failure; check for
                    # success markers and absence of error messages
                    if 'not found' in stat_out.lower():
                        continue
                    if ('Inode:' in stat_out or 'Type:' in stat_out
                            or 'Size:' in stat_out
                            or 'Links:' in stat_out):
                        display = config.KNOWN_GAMES.get(name, name)
                        self.log(f"Detected game: {display} ({name})",
                                 "success")
                        return name
                except CommandError:
                    pass

        # Fallback: list directory entries for unknown games
        try:
            output = self._debugfs_run(
                f'ls -p "{config.GAME_BASE_PATH}"', timeout=15)
            self.log(f"debugfs ls -p output: {output[:500]}", "info")
        except CommandError:
            return None

        for line in output.splitlines():
            parsed = self._parse_debugfs_ls_line(line.strip())
            if parsed is None:
                continue
            _inode, _mode, name = parsed
            if name.isdigit():
                continue
            try:
                stat_out = self._debugfs_run(
                    f'stat "{config.GAME_BASE_PATH}/{name}/edata"',
                    timeout=10)
                if 'not found' in stat_out.lower():
                    continue
                if ('Inode:' in stat_out or 'Type:' in stat_out
                        or 'Size:' in stat_out):
                    display = config.KNOWN_GAMES.get(name, name)
                    self.log(f"Detected game: {display} ({name})",
                             "success")
                    return name
            except CommandError:
                pass
        return None

    def _debugfs_ls_recursive(self, path, result_list, _depth=0):
        """Recursively list files under a directory via debugfs.

        Logs the raw ``ls -p`` output for the top-level call and any
        empty subtree it descends into — the "Found 0 files" mac
        regression couldn't be diagnosed from the user log because
        we never captured what debugfs was actually returning.
        Bounded so a populated 10k-file tree doesn't flood the log:
        only the top-level dir AND any subtree that ends up empty
        get printed.
        """
        try:
            # Quote — JJP trees contain dirs like "Pyro Action Button".
            output = self._debugfs_run(
                f'ls -p "{path}"', timeout=15)
        except CommandError as e:
            self.log(
                f"[scan] debugfs ls failed for {path}: "
                f"{getattr(e, 'output', e) or e}", "info")
            return
        # Always log the top-level scan output verbatim so the
        # actual debugfs output format we're parsing is visible
        # in field logs.
        if _depth == 0:
            preview = (output if len(output) <= 800
                       else output[:800] + "…")
            self.log(
                f"[scan] raw ls -p {path} "
                f"({len(output)} chars):\n{preview}", "info")
        before_count = len(result_list)
        skipped_short_lines = 0
        subdir_count = 0
        file_count = 0
        for line in output.splitlines():
            parsed = self._parse_debugfs_ls_line(line.strip())
            if parsed is None:
                if line.strip() and not line.strip().startswith(
                        "debugfs"):
                    skipped_short_lines += 1
                continue
            _inode, mode, name = parsed
            # Mode field: directory = 04xxxx, file = 10xxxx
            full_path = f"{path}/{name}"
            if mode.startswith('04'):
                # Directory — recurse
                subdir_count += 1
                self._debugfs_ls_recursive(
                    full_path, result_list, _depth=_depth + 1)
            else:
                # File
                file_count += 1
                result_list.append(full_path)
        if _depth == 0 or (len(result_list) - before_count) == 0:
            self.log(
                f"[scan] {path}: {file_count} files here, "
                f"{subdir_count} subdirs, "
                f"{skipped_short_lines} short-line skips, "
                f"{len(result_list) - before_count} added recursively",
                "info")

    def _phase_copy_full_filesystem_native(self):
        """Copy non-edata system files via native debugfs dump."""
        self.log("Full filesystem dump via native debugfs...", "info")
        game_name = self.game_name or ""
        edata_rel = f"jjpe/gen1/{game_name}/edata"
        exclude_dirs = {edata_rel, "proc", "sys", "dev", "run", "tmp",
                        "lost+found"}

        all_files = []
        self._debugfs_ls_recursive_filtered(
            "/", all_files, exclude_dirs, prefix="")

        total = len(all_files)
        if total == 0:
            self.log("No system files found.", "info")
            return

        self.log(f"Found {total} system entries to copy.", "info")
        self.on_progress(0, total, "Copying system files...")

        sys_dir = os.path.join(self.output_path, "system")
        tmp_file = os.path.join(tempfile.gettempdir(),
                                f"jjp_sys_{uuid.uuid4().hex[:8]}.bin")
        copied = 0
        try:
            for i, fs_path in enumerate(all_files):
                self._check_cancel()
                out_path = os.path.join(sys_dir, fs_path.lstrip("/"))
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                try:
                    self._debugfs_run(
                        f'dump "{fs_path}" "{tmp_file}"', timeout=60)
                    if os.path.isfile(tmp_file):
                        import shutil
                        shutil.move(tmp_file, out_path)
                        copied += 1
                except (CommandError, OSError):
                    pass
                if (i + 1) % 200 == 0 or i + 1 == total:
                    self.on_progress(i + 1, total, f"Copied {copied} files")
        finally:
            try:
                os.unlink(tmp_file)
            except OSError:
                pass

        self.log(f"System dump complete: {copied} files copied.", "success")

    def _debugfs_ls_recursive_filtered(self, path, result_list,
                                       exclude_dirs, prefix=""):
        """Recursively list files, skipping excluded directories."""
        try:
            # Quote — paths may contain spaces; unquoted ls -p
            # tokenizes and debugfs returns its usage banner.
            output = self._debugfs_run(
                f'ls -p "{path}"', timeout=15)
        except CommandError:
            return
        for line in output.splitlines():
            parsed = self._parse_debugfs_ls_line(line.strip())
            if parsed is None:
                continue
            _inode, mode, name = parsed
            full_path = f"{path}/{name}" if path != "/" else f"/{name}"
            rel = full_path.lstrip("/")
            if mode.startswith('04'):
                if rel not in exclude_dirs:
                    self._debugfs_ls_recursive_filtered(
                        full_path, result_list, exclude_dirs, prefix)
            else:
                result_list.append(full_path)

    def _generate_checksums_native(self):
        """Generate .checksums.md5 (host-side, parallel)."""
        self.log("Generating checksums for asset tracking...", "info")
        try:
            self._write_checksums_parallel(self.output_path)
            self.log("Checksums saved to .checksums.md5 in output folder.",
                     "success")
        except OSError as e:
            self.log(f"Warning: Could not generate checksums ({e}). "
                     "Asset modification tracking will not be available.",
                     "info")

    def _discover_partitions(self, device):
        """Enumerate every partition on the device with metadata.

        Logs the full partition map so we always have the layout in
        the log file regardless of whether the auto-pick succeeds —
        Habo's bug report only ever surfaced partition 2 because the
        old picker returned the first match and bailed.  Now we log
        all of them.

        Returns a list of ``_PartitionInfo`` (one per partition) and
        also stashes it on ``self._partition_map`` for downstream
        consumers (error paths, A/B detection, the mount-retry loop).
        """
        from .executor import (WslExecutor, DockerExecutor,
                               NativeExecutor)

        if isinstance(self.executor, WslExecutor):
            parts = self._discover_partitions_windows(device)
        elif isinstance(self.executor, DockerExecutor):
            parts = self._discover_partitions_macos(device)
        elif isinstance(self.executor, NativeExecutor):
            parts = self._discover_partitions_linux(device)
        else:
            parts = []

        self._partition_map = parts
        if parts:
            self.log("Partition map:", "info")
            for p in parts:
                sz = (f"{p.size_bytes / 1e9:.2f} GB"
                      if p.size_bytes else "size ?")
                self.log(
                    f"  partition {p.number}: {p.raw_type} "
                    f"[{p.fs_kind}] {sz}",
                    "info")
        else:
            self.log(
                f"Could not enumerate partitions on {device} — "
                f"falling back to default "
                f"(partition {config.GAME_PARTITION_NUMBER}).",
                "info")
        return parts

    def _discover_partitions_windows(self, device):
        """Windows helper for _discover_partitions.

        Pipes Get-Partition through ForEach-Object to emit one
        ``num|type|size`` line per partition (avoiding Format-Table's
        column truncation), then hands the raw text to
        :func:`_parse_windows_partitions`.
        """
        disk_num = device.rstrip().replace("\\\\", "\\").split(
            "PHYSICALDRIVE")[-1]
        if not disk_num.isdigit():
            return []
        try:
            rc, out, _ = self.executor.run_host(
                f'powershell -NoProfile -Command "'
                f"Get-Partition -DiskNumber {disk_num} | "
                f"ForEach-Object {{ "
                f"'{{0}}|{{1}}|{{2}}' -f "
                f"$_.PartitionNumber, $_.Type, $_.Size }}"
                f'"',
                timeout=15)
        except Exception:
            return []
        if rc != 0:
            return []
        return _parse_windows_partitions(out)

    def _discover_partitions_macos(self, device):
        """macOS helper for _discover_partitions.

        Runs ``diskutil list <device>`` and hands the output to
        :func:`_parse_macos_partitions`.
        """
        try:
            rc, out, _ = self.executor.run_host(
                f"diskutil list {device}", timeout=10)
        except Exception:
            return []
        if rc != 0:
            return []
        return _parse_macos_partitions(out)

    def _discover_partitions_linux(self, device):
        """Linux helper for _discover_partitions.

        Runs ``lsblk -brno NAME,FSTYPE,SIZE`` (bytes, raw, no header)
        and hands the output to :func:`_parse_linux_partitions`.
        """
        try:
            result = self.executor.run(
                f"lsblk -brno NAME,FSTYPE,SIZE {device}", timeout=10)
        except Exception:
            return []
        return _parse_linux_partitions(result)

    def _detect_partition(self, device):
        """Pick a partition number to mount — backward-compat shim.

        Honors ``self.partition_override`` first (the manual escape
        hatch).  Otherwise calls ``_discover_partitions``, picks the
        largest ``fs_kind == "linux"`` candidate (game data dwarfs
        OS/boot partitions on every JJP SSD layout we have data for),
        and populates ``self._ab_partitions`` with same-sized peers.

        Returns a single int so existing callers (the macOS Docker
        path, ``RestoreToSSDPipeline``) don't have to change.  The
        Windows ``_mount_ssd`` path now does content-verification on
        top of this and can override the pick if ``/jjpe/gen1`` is
        missing on the chosen partition.
        """
        if self.partition_override is not None:
            self.log(
                f"Manual partition override: using partition "
                f"{self.partition_override} "
                f"(skipping auto-discovery)",
                "info")
            # Still enumerate so the partition map is in the log.
            self._discover_partitions(device)
            return int(self.partition_override)

        parts = self._discover_partitions(device)
        linux_parts = [p for p in parts if p.fs_kind == "linux"]
        if linux_parts:
            best = max(linux_parts, key=lambda p: p.size_bytes)
            self.log(
                f"Auto-detected largest Linux partition: partition "
                f"{best.number} ({best.size_bytes / 1e9:.2f} GB)",
                "info")
            self._ab_partitions = None
            if best.size_bytes > 1e9:  # >1 GB — sanity guard
                peers = [
                    p.number for p in linux_parts
                    if p.number != best.number
                    and p.size_bytes > 0
                    and abs(p.size_bytes - best.size_bytes)
                        / best.size_bytes < 0.05
                ]
                if peers:
                    self._ab_partitions = [best.number] + peers
                    self.log(
                        f"Detected A/B partition layout: "
                        f"partitions {self._ab_partitions}",
                        "info")
            return best.number

        self.log(
            f"No Linux partition identified — falling back to "
            f"default (partition {config.GAME_PARTITION_NUMBER}).",
            "info")
        return config.GAME_PARTITION_NUMBER

    # ------------------------------------------------------------------
    # Windows mount path: enumerate → content-verify → retry
    # ------------------------------------------------------------------

    def _build_partition_candidates(self, device):
        """Build the ordered list of partition numbers to try on Windows.

        Manual override → just that one partition.  Otherwise: every
        Linux-fs candidate sorted largest-first (game data dwarfs
        OS/boot on every JJP layout we've seen, and same-sized peers
        auto-fall through as A/B fallbacks).  Anything Windows
        flagged as a non-Linux unknown type comes after as a last
        resort — gives us a fighting chance if our type-mapping
        table misses an edge case.
        """
        if self.partition_override is not None:
            self.log(
                f"Manual partition override: trying only partition "
                f"{self.partition_override}",
                "info")
            # Still enumerate so the partition map is in the log.
            self._discover_partitions(device)
            return [int(self.partition_override)]

        parts = self._discover_partitions(device)
        linux = sorted(
            (p for p in parts if p.fs_kind == "linux"),
            key=lambda p: p.size_bytes, reverse=True)
        seen = {p.number for p in linux}
        # Pure safety net — anything mysterious that isn't obviously
        # not-Linux (EFI, swap, MSR).  In practice empty on Windows.
        other = sorted(
            (p for p in parts
             if p.number not in seen
             and p.fs_kind not in ("efi", "swap", "msr", "ntfs")),
            key=lambda p: p.size_bytes, reverse=True)
        candidates = [p.number for p in linux] + [p.number for p in other]
        if not candidates:
            # Totally mysterious drive — fall back to default so
            # behaviour matches pre-refactor and gives the user a
            # clear error if it's wrong.
            candidates = [config.GAME_PARTITION_NUMBER]
        return candidates

    def _update_ab_partitions_for(self, winning_part_num):
        """Recompute ``_ab_partitions`` around the partition that won.

        Called after content-verify so the A/B partner list reflects
        whichever slot we ended up using, not whichever the
        largest-wins heuristic guessed first.
        """
        parts = self._partition_map or []
        win = next(
            (p for p in parts if p.number == winning_part_num), None)
        if not win or win.size_bytes <= 1e9:
            self._ab_partitions = None
            return
        peers = [
            p.number for p in parts
            if p.number != winning_part_num
            and p.fs_kind == "linux"
            and p.size_bytes > 0
            and abs(p.size_bytes - win.size_bytes)
                / win.size_bytes < 0.05
        ]
        if peers:
            self._ab_partitions = [winning_part_num] + peers
            self.log(
                f"A/B partition layout: partitions "
                f"{self._ab_partitions} (primary = {winning_part_num})",
                "info")
        else:
            self._ab_partitions = None

    def _format_partition_map_for_error(self):
        """One-line-per-partition summary suitable for an error body."""
        parts = self._partition_map or []
        if not parts:
            return "(no partition map captured)"
        lines = ["Partition map:"]
        for p in parts:
            sz = (f"{p.size_bytes / 1e9:.2f} GB"
                  if p.size_bytes else "size ?")
            lines.append(
                f"  partition {p.number}: {p.raw_type} "
                f"[{p.fs_kind}] {sz}")
        return "\n".join(lines)

    def _wsl_bring_disk_online(self, disk_num):
        """Bring the SSD back online (cleanup path).

        Idempotent — safe to call even if we never offlined it.
        """
        if (getattr(self, '_disk_was_offlined', False)
                and disk_num.isdigit()):
            self.executor.run_host(
                f'powershell -NoProfile -Command '
                f'"Set-Disk -Number {disk_num} -IsOffline $false"',
                timeout=15)
            self._disk_was_offlined = False

    def _diagnostic_dump_boot_partitions_windows(self):
        """Peek inside small FAT/EFI partitions on the SSD.

        JJP machines that A/B-swap update slots almost certainly
        track the active slot somewhere — a ``current_slot.txt`` on
        the EFI System Partition, a GRUB env, a U-Boot env block,
        etc.  We don't know which yet because the existing pipeline
        never looked.  This method dumps the top two levels of every
        small (< 200 MB) FAT or EFI partition into the log so we can
        spot the pattern from real-world drives and light up actual
        active-slot detection in a follow-up release.

        Best-effort: any failure here is silently skipped (logged but
        not raised) — diagnostics aren't worth aborting the main
        flow.  Runs while the disk is already offline (after the
        one-time setup in ``_mount_ssd_windows``) but BEFORE the
        candidate mount loop, so we don't have to juggle which
        partitions are currently attached to WSL.
        """
        device = self.device_path
        parts = self._partition_map or []
        candidates = [p for p in parts
                      if p.fs_kind in ("fat", "efi")
                      and 0 < p.size_bytes < 200 * 1024 * 1024]
        if not candidates:
            return
        self.log("Boot-partition diagnostic dump (FAT/EFI):", "info")
        for p in candidates:
            try:
                rc, stdout, stderr = self.executor.run_host(
                    f'wsl --mount "{device}" --partition {p.number} '
                    f'--type vfat --options "ro"',
                    timeout=30)
                if rc != 0:
                    self.log(
                        f"  partition {p.number} ({p.raw_type}): "
                        f"could not mount as vfat — skipping "
                        f"({(stderr or stdout or '').strip()[:120]})",
                        "info")
                    continue
                try:
                    result = self.executor.run(
                        "findmnt -rn -o TARGET -t vfat | "
                        "grep -v '/mnt/c'",
                        timeout=10)
                    mounts = [m.strip() for m in
                              result.strip().split("\n") if m.strip()]
                except CommandError:
                    mounts = []
                if mounts:
                    mp = mounts[-1]
                    try:
                        # Top 2 levels.  -maxdepth 2 picks up
                        # grub/grub.cfg, EFI/<vendor>/*.efi, etc.
                        # Cap at 50 entries so an unexpectedly busy
                        # boot partition doesn't bloat the log.
                        out = self.executor.run(
                            f"find '{mp}' -maxdepth 2 -mindepth 1 "
                            f"-printf '%P\\n' 2>/dev/null | "
                            f"sort | head -50",
                            timeout=10)
                        listing = [ln for ln in
                                   out.strip().splitlines()
                                   if ln.strip()]
                        p.boot_listing = listing
                        self.log(
                            f"  partition {p.number} ({p.raw_type}) "
                            f"at {mp}:",
                            "info")
                        if listing:
                            for entry in listing:
                                self.log(f"    {entry}", "info")
                        else:
                            self.log("    (empty)", "info")
                    except CommandError as e:
                        self.log(
                            f"  partition {p.number}: ls failed — "
                            f"{(e.output or '')[:120]}",
                            "info")
                self.executor.run_host(
                    f'wsl --unmount "{device}"', timeout=15)
            except Exception as e:
                self.log(
                    f"  partition {p.number}: diagnostic dump "
                    f"failed — {e}",
                    "info")
                # Best-effort cleanup so the main mount can proceed.
                try:
                    self.executor.run_host(
                        f'wsl --unmount "{device}"', timeout=15)
                except Exception:
                    pass

    def _mount_ssd_windows(self, read_only):
        """Windows: enumerate → content-verify each candidate → win.

        The flow:
          1. One-time setup — clean stale WSL mounts, take the disk
             offline so Windows releases any drive-letter hold.
          2. Build the candidate list (manual override > largest
             Linux > same-sized A/B peers > non-Linux fallbacks).
          3. ``wsl --mount`` each candidate; if it has /jjpe/gen1,
             we keep it mounted and return.  If not, ``wsl --unmount``
             and try the next.
          4. If every candidate misses, bring the disk back online
             and raise with the partition map in the error so the
             user can use the manual override.

        Why the loop instead of a single pick: Habo's drive had
        partition 2 enumerate as Linux but partition 3 was the
        actual game data.  The old code's first-Unknown-wins pick
        landed on 2, mounted it fine, and *then* failed validation.
        Trying each candidate in turn solves that without needing
        to know JJP's specific partition layout.
        """
        device = self.device_path  # e.g. \\.\PHYSICALDRIVE2
        self._wsl_mount_device = device
        disk_num = device.rstrip().replace(
            "\\\\", "\\").split("PHYSICALDRIVE")[-1]

        # --- One-time setup ------------------------------------------
        # Clean up stale WSL mounts and Windows drive locks before
        # attempting wsl --mount.  Order matters:
        #   1. Try wsl --unmount (specific device) while disk is online
        #   2. Fallback: wsl --unmount (ALL disks) if specific failed
        #   3. Take disk offline to release Windows drive letters
        rc_u, _, _ = self.executor.run_host(
            f'wsl --unmount "{device}"', timeout=15)
        if rc_u != 0:
            self.executor.run_host('wsl --unmount', timeout=15)

        if disk_num.isdigit():
            self.log("Taking disk offline for WSL access...", "info")
            rc_off, _, err_off = self.executor.run_host(
                f'powershell -NoProfile -Command '
                f'"Set-Disk -Number {disk_num} -IsOffline $true"',
                timeout=15)
            if rc_off != 0:
                self.log(
                    f"Warning: could not take disk offline: {err_off}",
                    "info")
            self._disk_was_offlined = True
        else:
            self._disk_was_offlined = False

        # --- Build the candidate list --------------------------------
        candidates = self._build_partition_candidates(device)

        # --- Boot-partition diagnostic (data collection) -------------
        # Runs BEFORE the candidate loop so the FAT/EFI mount/unmount
        # cycles don't fight with the game-data slot we're about to
        # attach — `wsl --unmount <device>` unmounts all partitions
        # on the disk, so we can't safely peek at the EFI while a
        # game partition is mounted.
        try:
            self._diagnostic_dump_boot_partitions_windows()
        except Exception as e:
            # Diagnostic — never fatal.
            self.log(
                f"Boot-partition diagnostic skipped ({e}).", "info")

        # --- Try each candidate --------------------------------------
        attempted = []
        for part_num in candidates:
            attempted.append(part_num)
            self.log(
                f"Attaching {device} partition {part_num} to WSL...",
                "info")

            mount_cmd = (
                f'wsl --mount "{device}" --partition {part_num} '
                f'--type ext4')
            if read_only:
                mount_cmd += ' --options "ro"'
            rc, stdout, stderr = self.executor.run_host(
                mount_cmd, timeout=30)

            # Stale-mount recovery (preserved from the pre-refactor
            # code): wsl --shutdown clears stuck mounts in the WSL VM.
            if rc != 0 and "ALREADY_MOUNTED" in (
                    stderr or stdout or "").upper():
                self.log(
                    "Stale WSL mount detected — restarting WSL...",
                    "info")
                self.executor.run_host('wsl --shutdown', timeout=30)
                if disk_num.isdigit():
                    self.executor.run_host(
                        f'powershell -NoProfile -Command '
                        f'"Set-Disk -Number {disk_num} -IsOffline $true"',
                        timeout=15)
                rc, stdout, stderr = self.executor.run_host(
                    mount_cmd, timeout=30)

            if rc != 0:
                # Mount itself failed — log and try next candidate.
                # Common causes: partition isn't actually ext4
                # (Windows reported "Unknown" but it's, say, swap), or
                # USB drives on some systems.
                self.log(
                    f"  partition {part_num}: wsl --mount failed "
                    f"({(stderr or stdout or '').strip()[:200]})",
                    "info")
                continue

            # Find the mount point — wsl --mount puts it at
            # /mnt/wsl/<diskname>.  The most-recently-added ext4
            # mount on the WSL side is ours.
            try:
                result = self.executor.run(
                    # Positively match /mnt/wsl/ — that's where
                    # `wsl --mount` attaches physical disks.  A bare
                    # `grep -v '/mnt/c'` also lets WSLg's own ext4
                    # distro root (/mnt/wslg/distro) through, and on a
                    # post-`wsl --shutdown` restart that can sort last
                    # so mounts[-1] picks it instead of the partition —
                    # then the /jjpe/gen1 check fails on the distro
                    # root and we wrongly skip a real game slot.
                    "findmnt -rn -o TARGET -t ext4 | grep '/mnt/wsl/'",
                    timeout=10)
                mounts = [m.strip() for m in result.strip().split("\n")
                          if m.strip()]
            except CommandError:
                mounts = []
            if not mounts:
                self.log(
                    f"  partition {part_num}: attached but mount "
                    f"point not visible in WSL",
                    "info")
                self.executor.run_host(
                    f'wsl --unmount "{device}"', timeout=15)
                continue
            mp = mounts[-1]

            # Content-verify: does this partition contain a JJP game?
            try:
                self.executor.run(
                    f"test -d '{mp}{config.GAME_BASE_PATH}'",
                    timeout=10)
            except CommandError:
                self.log(
                    f"  partition {part_num}: mounted at {mp} but "
                    f"{config.GAME_BASE_PATH} not present — trying "
                    f"next",
                    "info")
                self.executor.run_host(
                    f'wsl --unmount "{device}"', timeout=15)
                continue

            # Capture mtime as a freshness signal.  Today it's only
            # logged; once A/B-mirror writes are wired up on Windows,
            # newer-mtime breaks the tie when both slots are present.
            mtime = 0
            try:
                mtime_out = self.executor.run(
                    f"stat -c %Y '{mp}{config.GAME_BASE_PATH}' "
                    "2>/dev/null", timeout=5).strip()
                if mtime_out:
                    mtime = int(mtime_out)
            except (CommandError, ValueError):
                pass

            # Success — keep this one mounted.
            self._part_num = part_num
            self.mount_point = mp
            self._ssd_mounted = True
            self._update_ab_partitions_for(part_num)
            mtime_str = f", mtime {mtime}" if mtime else ""
            self.log(
                f"SSD mounted at {mp} (partition {part_num} — "
                f"contains {config.GAME_BASE_PATH}{mtime_str})",
                "success")
            return

        # --- Exhausted every candidate -------------------------------
        self._wsl_bring_disk_online(disk_num)
        map_str = self._format_partition_map_for_error()
        raise PipelineError(
            "Mount",
            f"This doesn't look like a JJP game drive.\n"
            f"Tried partition(s): {attempted}.\n"
            f"{config.GAME_BASE_PATH} not found on any of them.\n\n"
            f"{map_str}\n\n"
            f"If you know the right partition number, set it in the "
            f'"Force partition #" field on the Direct-SSD panel '
            f"and re-run.\nOtherwise, make sure you selected the "
            f"correct drive.")

    def _mount_ssd(self, read_only=True):
        """Mount the SSD's game partition via platform-specific method.

        Windows takes a separate code path: ``_mount_ssd_windows``
        runs a content-verify retry loop because Habo's report showed
        that picking one partition by heuristic isn't enough — we
        have to look at what's actually on each candidate.  macOS and
        Linux keep the simpler single-pick-then-validate flow they've
        always had (their auto-pick has held up so far; if/when it
        misses we'll port the retry loop there too).
        """
        from .executor import WslExecutor, DockerExecutor, NativeExecutor

        if isinstance(self.executor, WslExecutor):
            # Handles its own partition pick, mount, content-verify,
            # error reporting, and disk-online cleanup.
            self._mount_ssd_windows(read_only)
            return

        # Non-Windows: pick one partition and try it.  The trailing
        # /jjpe/gen1 check at the bottom catches a wrong pick.
        part_num = self._detect_partition(self.device_path)
        self._part_num = part_num  # save for cleanup writeback

        tag = uuid.uuid4().hex[:8]
        self.mount_point = f"{config.MOUNT_PREFIX}ssd_{tag}"

        if isinstance(self.executor, DockerExecutor):
            # macOS: check for native debugfs (Homebrew e2fsprogs) to
            # access the SSD directly without copying the partition.
            device = self.device_path  # e.g. /dev/disk2
            dev_partition = f"{device}s{part_num}"
            raw_dev = device.replace("/dev/disk", "/dev/rdisk") + f"s{part_num}"

            # Unmount from macOS first
            rc, stdout, stderr = self.executor.run_host(
                f"diskutil unmountDisk {device}", timeout=15)
            if rc != 0:
                self.log(f"Warning: could not unmount {device}: {stderr}",
                         "info")

            # Get partition size for logging
            try:
                rc, info, _ = self.executor.run_host(
                    f"diskutil info {dev_partition}", timeout=10)
                m = re.search(r'Disk Size:\s*([\d.]+ [A-Z]+)', info or "")
                if m:
                    self.log(f"Partition size: {m.group(1)}", "info")
            except Exception:
                pass

            native_debugfs = _find_native_debugfs()
            if native_debugfs:
                # ── Native debugfs mode ──
                # Access the SSD partition directly via debugfs on the host.
                # No Docker, no partition copy — like WSL on Windows.
                self._native_debugfs_path = native_debugfs
                self._wsl_img = raw_dev  # debugfs operates on raw device
                self._ssd_image_path = None
                self._ssd_image_on_host = True
                self._needs_writeback = False  # changes are direct

                self.log(f"Using native debugfs: {native_debugfs}", "info")

                # Validate ext4 — debugfs may return exit 0 even on
                # permission denied, so check the output text too
                try:
                    stats_out = self._debugfs_run("stats", timeout=30)
                except CommandError as e:
                    stats_out = e.output or ""

                if ('permission denied' in stats_out.lower()
                        or 'filesystem not open' in stats_out.lower()):
                    # Raw disk access needs root on macOS.  Enable
                    # elevated mode — _debugfs_run_elevated uses
                    # osascript "with administrator privileges" which
                    # shows the standard macOS password dialog and
                    # caches the auth for ~5 minutes.
                    self.log("Permission denied — will request admin "
                             "privileges via macOS dialog...", "info")
                    self._use_sudo = True
                    try:
                        stats_out = self._debugfs_run(
                            "stats", timeout=30)
                        self.log("Admin privileges granted.", "success")
                    except CommandError as e:
                        raise PipelineError("Mount",
                            f"Could not access disk with admin "
                            f"privileges:\n{e.output}") from e

                if 'Filesystem features' not in stats_out:
                    raise PipelineError("Mount",
                        f"Cannot read ext4 filesystem on {raw_dev}:\n"
                        f"{stats_out[:300]}")
                self.log("ext4 filesystem validated.", "success")

                # Detect game name via debugfs on this slot.
                self.game_name = self._detect_game_via_debugfs()

                # A/B content-verify: JJP firmware uses asymmetric
                # A/B slots — one slot is active with a populated
                # /jjpe/gen1/<game>/edata, the other is prepared as
                # a directory tree but never written to.  The
                # largest-Linux picker can land on either one
                # (max() of equal-sized partitions returns the first
                # in iteration order).  If the edata on the picked
                # slot is empty, swap to the A/B partner.  Empirical
                # data from a GnR drive: partition 3 had the
                # directory but Size: 40 (empty); partition 5 was
                # the populated one with mtime Jul 2025.
                self.log(
                    f"A/B content-verify: game={self.game_name!r}, "
                    f"_ab_partitions={getattr(self, '_ab_partitions', None)}, "
                    f"current part={self._part_num}",
                    "info")
                if (self.game_name
                        and getattr(self, '_ab_partitions', None)):
                    edata_dir = (
                        f"{config.GAME_BASE_PATH}/"
                        f"{self.game_name}/edata")
                    is_pop = self._edata_is_populated(edata_dir)
                    self.log(
                        f"A/B content-verify verdict for "
                        f"partition {self._part_num}: "
                        f"populated={is_pop}",
                        "info")
                    if not is_pop:
                        partners = [
                            p for p in self._ab_partitions
                            if p != self._part_num]
                        for partner in partners:
                            partner_dev = device.replace(
                                "/dev/disk", "/dev/rdisk"
                            ) + f"s{partner}"
                            self.log(
                                f"Partition {self._part_num}: "
                                f"{self.game_name}/edata is empty "
                                f"— trying A/B partner partition "
                                f"{partner} ({partner_dev})…",
                                "info")
                            self._wsl_img = partner_dev
                            self._part_num = partner
                            try:
                                stats_out = self._debugfs_run(
                                    "stats", timeout=30)
                            except CommandError:
                                continue
                            if 'Filesystem features' not in stats_out:
                                continue
                            game = self._detect_game_via_debugfs()
                            if not game:
                                continue
                            self.game_name = game
                            new_edata = (
                                f"{config.GAME_BASE_PATH}/"
                                f"{game}/edata")
                            if self._edata_is_populated(new_edata):
                                self.log(
                                    f"Partner partition {partner} "
                                    f"has populated {game}/edata — "
                                    f"using it.",
                                    "success")
                                break
                            else:
                                self.log(
                                    f"Partner partition {partner} "
                                    f"also has empty edata — "
                                    f"trying next.",
                                    "info")

                if not read_only:
                    # Mod mode: set up local temp dir for staging
                    tag = uuid.uuid4().hex[:8]
                    self._debugfs_tmp = tempfile.mkdtemp(
                        prefix=f"jjp_debugfs_{tag}_")

                self.mount_point = None
                self._ssd_mounted = True  # signal for cleanup
                self.log("Direct SSD access ready (native debugfs).",
                         "success")
                return  # skip mount_point validation below

            # ── Docker fallback (no native debugfs) ──
            # Stream the partition into the Docker VM's filesystem.
            self.log("Native debugfs not found, falling back to Docker...",
                     "info")
            self.log(f"Preparing {device} for Docker access...", "info")

            host_paths = []
            if hasattr(self, 'output_path'):
                host_paths.append(self.output_path)
            if hasattr(self, 'assets_folder'):
                host_paths.append(self.assets_folder)
            self.log("Starting Docker container...", "info")
            self.executor.start_container(host_paths)

            # Image path inside the container (Docker VM filesystem)
            container_img = "/var/tmp/ssd_partition.img"
            self._ssd_image_on_host = False

            # Clean up stale images
            try:
                self.executor.run(
                    f"rm -f '{container_img}'", timeout=10)
            except CommandError:
                pass
            cache_dir = self.executor._cache_dir()
            stale_host_img = os.path.join(cache_dir, "ssd_partition.img")
            if os.path.exists(stale_host_img):
                try:
                    os.unlink(stale_host_img)
                except OSError:
                    pass

            self.log("Copying SSD partition to Docker VM (this may take "
                     "several minutes)...", "info")

            # Stream: dd on host -> pipe -> docker exec cat > file
            try:
                dd_proc = subprocess.Popen(
                    ["dd", f"if={raw_dev}", "bs=1048576"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                docker_proc = subprocess.Popen(
                    ["docker", "exec", "-i", "jjp-decryptor-worker",
                     "sh", "-c", f"cat > '{container_img}'"],
                    stdin=dd_proc.stdout,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                dd_proc.stdout.close()

                docker_out, docker_err = docker_proc.communicate(timeout=3600)
                dd_proc.wait(timeout=30)
                dd_stderr = dd_proc.stderr.read().decode(errors="replace")
                dd_proc.stderr.close()

                if dd_proc.returncode != 0:
                    err_text = dd_stderr
                    if "Permission denied" in err_text:
                        raise PipelineError("Mount",
                            f"Failed to read SSD partition via dd:\n"
                            f"{err_text}\n\n"
                            f"Raw block-device access needs elevation "
                            f"— relaunch Pinball Asset Decryptor with "
                            f"sudo (macOS/Linux) or right-click → "
                            f"Run as administrator (Windows).")
                    raise PipelineError("Mount",
                        f"Failed to read SSD partition via dd:\n{err_text}")
                if docker_proc.returncode != 0:
                    raise PipelineError("Mount",
                        "Failed to stream partition image into Docker:\n"
                        + docker_err.decode(errors="replace"))
            except PipelineError:
                raise
            except subprocess.TimeoutExpired:
                dd_proc.kill()
                docker_proc.kill()
                raise PipelineError("Mount",
                    "Timed out copying SSD partition to Docker VM.")
            except Exception as e:
                raise PipelineError("Mount",
                    f"Failed to copy SSD partition: {e}") from e

            # Verify the image arrived
            try:
                size_out = self.executor.run(
                    f"stat -c%s '{container_img}'", timeout=10).strip()
                img_size = int(size_out)
                self.log(f"Partition image: {img_size / (1024**3):.1f} GB",
                         "success")
            except (CommandError, ValueError):
                raise PipelineError("Mount",
                    "Partition image not found inside Docker container.")

            wsl_img = container_img
            self._ssd_image_path = None

            if read_only:
                # Decrypt mode: loop mount the image read-only
                try:
                    self.executor.run(
                        f"mkdir -p {self.mount_point}", timeout=10)
                    try:
                        self.executor.run(
                            f"mount -o loop,ro '{wsl_img}' "
                            f"{self.mount_point}",
                            timeout=config.MOUNT_TIMEOUT)
                    except CommandError:
                        self.log("Journal is dirty, mounting with "
                                 "noload...", "info")
                        self.executor.run(
                            f"mount -o loop,ro,noload '{wsl_img}' "
                            f"{self.mount_point}",
                            timeout=config.MOUNT_TIMEOUT)
                    self._ssd_mounted = True
                    self.log(f"Image mounted at {self.mount_point}", "success")
                except CommandError as e:
                    raise PipelineError("Mount",
                        f"Failed to mount SSD image:\n{e.output}") from e
            else:
                # Modify mode: use debugfs (no mount needed)
                self._wsl_img = wsl_img
                tag = uuid.uuid4().hex[:8]
                self._debugfs_tmp = f"/var/tmp/jjp_debugfs_{tag}"
                self.executor.run(
                    f"mkdir -p '{self._debugfs_tmp}'", timeout=10)

                # Validate ext4
                try:
                    stats_out = self._debugfs_run("stats", timeout=30)
                except CommandError as e:
                    stats_out = e.output or ""
                if ('permission denied' in stats_out.lower()
                        or 'filesystem not open' in stats_out.lower()
                        or 'Filesystem features' not in stats_out):
                    raise PipelineError("Mount",
                        f"SSD image is not a valid ext4 filesystem: "
                        f"{stats_out[:300]}")
                self.log("ext4 image validated.", "success")

                # Detect game name via debugfs
                self.game_name = self._detect_game_via_debugfs()

                self.mount_point = None
                self._ssd_mounted = True
                self.log("Image prepared for debugfs operations.", "success")
                return

        elif isinstance(self.executor, NativeExecutor):
            # Linux: direct mount
            device = self.device_path  # e.g. /dev/sdb
            dev_partition = f"{device}{part_num}"
            mount_opts = "ro" if read_only else "rw"
            self.log(f"Mounting {dev_partition} ({mount_opts})...", "info")
            try:
                self.executor.run(f"mkdir -p {self.mount_point}", timeout=10)
                self.executor.run(
                    f"mount -t ext4 -o {mount_opts} '{dev_partition}' "
                    f"{self.mount_point}",
                    timeout=config.MOUNT_TIMEOUT)
                self._ssd_mounted = True
                self.log(f"SSD mounted at {self.mount_point}", "success")
            except CommandError as e:
                raise PipelineError("Mount",
                    f"Failed to mount SSD:\n{e.output}") from e

        # Validate this looks like a JJP game partition
        try:
            self.executor.run(
                f"test -d '{self.mount_point}{config.GAME_BASE_PATH}'",
                timeout=10)
        except CommandError:
            raise PipelineError("Mount",
                f"This doesn't look like a JJP game drive.\n"
                f"Expected {config.GAME_BASE_PATH} not found on partition "
                f"{part_num}.\n\n"
                "Make sure you selected the correct drive.")

    def _cleanup_ssd(self):
        """Unmount the SSD and clean up."""
        self.log("Cleaning up...", "info")
        from .executor import WslExecutor, DockerExecutor

        if self._ssd_mounted:
            try:
                # Sync before unmount
                self.executor.run("sync", timeout=30)
            except CommandError:
                pass

            if isinstance(self.executor, WslExecutor) and self._wsl_mount_device:
                # Windows: detach disk from WSL so Windows can eject it
                dev = self._wsl_mount_device
                rc, stdout, stderr = self.executor.run_host(
                    f'wsl --unmount "{dev}"', timeout=30)
                if rc != 0:
                    # Targeted unmount may report failure if the A/B
                    # mirror swap left WSL tracking a different
                    # device handle, or if nothing's attached anymore
                    # — fall through to a global wsl --unmount to
                    # cover both cases.  Phrased as informational so
                    # users don't think anything went wrong on a
                    # successful run.
                    self.log("Releasing remaining WSL-attached disks...",
                             "info")
                    rc2, _, stderr2 = self.executor.run_host(
                        'wsl --unmount', timeout=30)
                    if rc2 != 0:
                        # Nuclear option: shut down WSL entirely
                        self.log("Forcing WSL shutdown to release disk...", "info")
                        self.executor.run_host('wsl --shutdown', timeout=30)
                # Bring the disk back online so Windows can see it again
                if getattr(self, '_disk_was_offlined', False):
                    disk_num = dev.rstrip().replace("\\\\", "\\").split(
                        "PHYSICALDRIVE")[-1]
                    if disk_num.isdigit():
                        self.executor.run_host(
                            f'powershell -NoProfile -Command '
                            f'"Set-Disk -Number {disk_num} -IsOffline $false"',
                            timeout=15)
                    self._disk_was_offlined = False
            elif isinstance(self.executor, DockerExecutor):
                if getattr(self, '_native_debugfs_path', None):
                    device = getattr(self, 'device_path', None)

                    # Run e2fsck on every partition we wrote to.
                    # debugfs -w bypasses the ext4 journal; without
                    # e2fsck the journal replay on next mount can
                    # revert our changes.  Skip entirely when this
                    # run never wrote to the SSD (read-only Extract):
                    # macOS raw-disk e2fsck often fails on the final
                    # superblock writeback with "Error writing file
                    # system info: Invalid argument" (rc=9), which
                    # was surfacing as a scary error on perfectly
                    # successful Extract runs.
                    wrote = getattr(self, '_wrote_to_ssd', False)
                    if device and getattr(self, '_succeeded', False) \
                            and wrote:
                        e2fsck = self._native_debugfs_path.replace(
                            'debugfs', 'e2fsck')
                        ab = getattr(self, '_ab_partitions', None)
                        part_num = getattr(self, '_part_num',
                                           config.GAME_PARTITION_NUMBER)
                        parts_to_fsck = (
                            ab if ab else [part_num])
                        for p in parts_to_fsck:
                            raw = device.replace(
                                "/dev/disk", "/dev/rdisk") + f"s{p}"
                            self.log(
                                f"Running e2fsck on {device}s{p} to "
                                f"commit journal...", "info")
                            try:
                                if getattr(self, '_use_sudo', False):
                                    # Reuse the cached admin password so
                                    # the cleanup phase doesn't pop a
                                    # fresh dialog per A/B partition.
                                    # Previously each e2fsck pass used
                                    # bare ``with administrator
                                    # privileges`` (no user/password
                                    # clause), which forced a re-prompt
                                    # per call — three total prompts on
                                    # a 2-slot A/B drive.
                                    #
                                    # ``osascript do shell script``
                                    # raises if the shell rc is
                                    # non-zero, but e2fsck legitimately
                                    # returns 1 when it fixed errors
                                    # (and 2 when filesystem changes
                                    # need a reboot — also acceptable
                                    # for our journal-replay use case).
                                    # Capture rc explicitly and exit 0
                                    # for the 0/1/2 happy band, letting
                                    # higher rcs propagate as real
                                    # failures.
                                    shell_cmd = (
                                        f"'{e2fsck}' -fy '{raw}' 2>&1; "
                                        f"rc=$?; "
                                        f"echo __E2FSCK_RC=$rc; "
                                        f"[ $rc -le 2 ] && exit 0 "
                                        f"|| exit $rc")
                                    out = self._run_shell_elevated(
                                        shell_cmd, timeout=300,
                                        label=f"e2fsck {device}s{p}")
                                    m = re.search(
                                        r"__E2FSCK_RC=(\d+)", out)
                                    rc = int(m.group(1)) if m else 0
                                    if rc <= 1:
                                        self.log(
                                            f"e2fsck {device}s{p}: OK",
                                            "success")
                                    else:
                                        self.log(
                                            f"e2fsck {device}s{p} "
                                            f"returned {rc} "
                                            f"(filesystem changed — "
                                            f"may need reboot)",
                                            "info")
                                else:
                                    result = subprocess.run(
                                        [e2fsck, "-fy", raw],
                                        capture_output=True, text=True,
                                        encoding='utf-8', errors='replace',
                                        timeout=300)
                                    # e2fsck returns 1 if it fixed
                                    # errors, 0 if clean — both are OK.
                                    if result.returncode <= 1:
                                        self.log(
                                            f"e2fsck {device}s{p}: OK",
                                            "success")
                                    else:
                                        self.log(
                                            f"e2fsck {device}s{p} returned "
                                            f"{result.returncode}: "
                                            f"{result.stderr[:200]}",
                                            "info")
                            except FileNotFoundError:
                                self.log(
                                    f"e2fsck not found at {e2fsck} — "
                                    f"skipping journal fix", "info")
                            except Exception as e:
                                # macOS e2fsck-via-osascript regularly hits
                                # ``Error writing file system info: Invalid
                                # argument`` after FILE SYSTEM WAS MODIFIED.
                                # That's the superblock free-block counter
                                # rewrite failing because DiskArbitration
                                # is still holding the device write-locked
                                # after our writes — the actual file data
                                # is intact (we verified CRC32s pre-fsck),
                                # only the cached free-block count is off
                                # by the net inode-allocation delta.  The
                                # kernel recomputes it from the bitmap on
                                # next mount, so the discrepancy is purely
                                # cosmetic.  Surface this as INFO with the
                                # explanation rather than as a scary error.
                                err_text = str(e)
                                is_benign_macos = (
                                    "Error writing file system info"
                                    in err_text
                                    and "FILE SYSTEM WAS MODIFIED"
                                    in err_text)
                                if is_benign_macos:
                                    self.log(
                                        f"e2fsck {device}s{p}: journal "
                                        f"committed; superblock free-"
                                        f"count rewrite blocked by macOS "
                                        f"DiskArbitration (expected — "
                                        f"file data is intact, kernel "
                                        f"recomputes on next mount).",
                                        "info")
                                else:
                                    self.log(
                                        f"e2fsck {device}s{p} failed: {e}",
                                        "info")

                    # Sync and eject so macOS flushes all writes
                    try:
                        self.executor.run_host("sync", timeout=30)
                    except Exception:
                        pass
                    if device:
                        try:
                            rc, _, stderr = self.executor.run_host(
                                f"diskutil eject {device}", timeout=30)
                            if rc == 0:
                                self.log(
                                    f"Disk {device} ejected — safe to "
                                    f"remove.", "success")
                            else:
                                self.log(
                                    f"Warning: could not eject {device}: "
                                    f"{stderr}", "info")
                        except Exception:
                            pass

                    # Clean up local temp dir
                    if hasattr(self, '_debugfs_tmp') and \
                            os.path.isdir(self._debugfs_tmp):
                        import shutil as _shutil
                        try:
                            _shutil.rmtree(self._debugfs_tmp,
                                           ignore_errors=True)
                        except Exception:
                            pass
                else:
                    # Docker mode: unmount loop mount or clean debugfs tmp
                    if self.mount_point:
                        try:
                            self.executor.run(
                                f"umount '{self.mount_point}' "
                                f"2>/dev/null; true",
                                timeout=30)
                        except CommandError:
                            pass
                        try:
                            self.executor.run(
                                f"rmdir '{self.mount_point}' "
                                f"2>/dev/null; true",
                                timeout=5)
                        except CommandError:
                            pass
                    if hasattr(self, '_debugfs_tmp'):
                        try:
                            self.executor.run(
                                f"rm -rf '{self._debugfs_tmp}' "
                                f"2>/dev/null; true",
                                timeout=10)
                        except CommandError:
                            pass
            else:
                # Linux: unmount inside executor
                try:
                    self.executor.run(
                        f"umount '{self.mount_point}' 2>/dev/null; true",
                        timeout=30)
                except CommandError:
                    pass
                try:
                    self.executor.run(
                        f"rmdir '{self.mount_point}' 2>/dev/null; true",
                        timeout=5)
                except CommandError:
                    pass

            self._ssd_mounted = False

        # Write modified image back to SSD (macOS Docker modify mode)
        _img_in_container = not getattr(self, '_ssd_image_on_host', True)
        _needs_wb = (getattr(self, '_needs_writeback', False)
                     and getattr(self, '_succeeded', False))

        if _needs_wb and _img_in_container:
            # Image lives inside Docker VM — stream it back to SSD
            device = self.device_path
            part_num = getattr(self, '_part_num', config.GAME_PARTITION_NUMBER)
            raw_dev = device.replace("/dev/disk", "/dev/rdisk") + f"s{part_num}"
            container_img = "/var/tmp/ssd_partition.img"
            self.log("Writing modified image back to SSD (this may take "
                     "several minutes)...", "info")
            self.executor.run_host(
                f"diskutil unmountDisk {device}", timeout=15)
            import subprocess as _sp
            try:
                docker_proc = _sp.Popen(
                    ["docker", "exec", "jjp-decryptor-worker",
                     "cat", container_img],
                    stdout=_sp.PIPE, stderr=_sp.PIPE)
                dd_proc = _sp.Popen(
                    ["dd", f"of={raw_dev}", "bs=1048576"],
                    stdin=docker_proc.stdout, stdout=_sp.PIPE, stderr=_sp.PIPE)
                docker_proc.stdout.close()

                dd_out, dd_err = dd_proc.communicate(timeout=3600)
                docker_proc.wait(timeout=30)

                if dd_proc.returncode != 0 or docker_proc.returncode != 0:
                    err = dd_err.decode(errors="replace")
                    self.log(f"WARNING: Failed to write image back to SSD!\n"
                             f"{err}\n\n"
                             f"The modified image is preserved inside the "
                             f"Docker container at {container_img}.\n"
                             f"Do NOT stop Docker until you have recovered it.",
                             "error")
                else:
                    self.executor.run_host("sync", timeout=30)
                    self.log("Image written back to SSD successfully.",
                             "success")
                    self._writeback_ok = True
            except _sp.TimeoutExpired:
                self.log("WARNING: Timed out writing image back to SSD!\n"
                         f"The modified image is preserved inside the "
                         f"Docker container at {container_img}.",
                         "error")
            except Exception as e:
                self.log(f"WARNING: Failed to write image back to SSD: {e}",
                         "error")

        elif (_needs_wb and self._ssd_image_path
                and os.path.isfile(self._ssd_image_path)):
            # Image lives on host filesystem (legacy path)
            device = self.device_path
            part_num = getattr(self, '_part_num', config.GAME_PARTITION_NUMBER)
            raw_dev = device.replace("/dev/disk", "/dev/rdisk") + f"s{part_num}"
            self.log("Writing modified image back to SSD (this may take "
                     "several minutes)...", "info")
            self.executor.run_host(
                f"diskutil unmountDisk {device}", timeout=15)
            rc, stdout, stderr = self.executor.run_host(
                f"dd if='{self._ssd_image_path}' of='{raw_dev}' bs=1m",
                timeout=3600)
            if rc != 0:
                self.log(f"WARNING: Failed to write image back to SSD!\n"
                         f"{stderr or stdout}\n\n"
                         f"The modified image is preserved at:\n"
                         f"{self._ssd_image_path}\n"
                         f"You can write it manually with:\n"
                         f"  sudo dd if='{self._ssd_image_path}' "
                         f"of='{raw_dev}' bs=1m",
                         "error")
            else:
                self.executor.run_host("sync", timeout=30)
                self.log("Image written back to SSD successfully.", "success")
                self._writeback_ok = True

        # Clean up temp image file
        # Keep it only if writeback was needed but failed (so user can
        # manually dd it)
        writeback_failed = (getattr(self, '_needs_writeback', False)
                            and not getattr(self, '_writeback_ok', False))
        if (self._ssd_image_path and os.path.isfile(self._ssd_image_path)
                and not writeback_failed):
            try:
                os.unlink(self._ssd_image_path)
            except OSError:
                pass
        # Clean up container-internal image (unless writeback failed)
        if _img_in_container and not writeback_failed:
            try:
                self.executor.run(
                    "rm -f /var/tmp/ssd_partition.img 2>/dev/null; true",
                    timeout=15)
            except (CommandError, Exception):
                pass

        # Stop Docker container if applicable (not used in native mode)
        if isinstance(self.executor, DockerExecutor) \
                and not getattr(self, '_native_debugfs_path', None):
            try:
                self.executor.stop_container()
            except Exception:
                pass

        self.log("Cleanup complete.", "success")


class DirectSSDModPipeline(StandaloneModPipeline):
    """Modify files directly on a physically-connected JJP game SSD.

    Skips the ISO extract, convert, and build phases. Writes encrypted
    files directly to the SSD's ext4 partition.

    Phases: Scan → Mount → Encrypt → Cleanup
    """

    def __init__(self, device_path, assets_folder, fl_dat_path,
                 log_cb, phase_cb, progress_cb, done_cb,
                 skip_duration_match=False, partition_override=None,
                 keep_full_length_paths=None):
        super().__init__(device_path, assets_folder, fl_dat_path,
                         log_cb, phase_cb, progress_cb, done_cb,
                         skip_duration_match=skip_duration_match,
                         keep_full_length_paths=keep_full_length_paths)
        self.device_path = device_path
        # See DirectSSDDecryptPipeline.partition_override.
        self.partition_override = partition_override
        self._ssd_mounted = False
        self._wsl_mount_device = None
        self._ssd_image_path = None
        self._needs_writeback = False
        self._disk_was_offlined = False
        self._partition_map = []
        self._ab_partitions = None

    def run(self):
        """Execute the direct SSD mod pipeline."""
        from .executor import DockerExecutor
        cleanup_phase = len(config.DIRECT_SSD_MOD_PHASES) - 1
        try:
            self._log_system_diagnostics()
            self.log(f"Direct SSD mod mode — device: {self.device_path}", "info")

            # Verify assets folder is accessible
            ok, msg = self.executor.check_path_accessible(self.assets_folder)
            if not ok:
                raise PipelineError("Scan", f"Assets folder path error:\n{msg}")

            self.on_phase(0)  # Scan
            self._phase_scan()
            self._check_cancel()

            if not self.changed_files:
                self.on_done(True,
                    "No changes detected in the assets folder.\n"
                    "Modify files in the output folder and try again.")
                return

            self.on_phase(1)  # Mount
            # Reuse DirectSSDDecryptPipeline's mount logic
            self._mount_ssd(read_only=False)
            self._check_cancel()

            self.on_phase(2)  # Encrypt
            if isinstance(self.executor, DockerExecutor):
                # macOS: use debugfs to write to raw image / raw device
                self._phase_encrypt_standalone()
                # Native debugfs writes directly to SSD — no writeback.
                # Docker mode writes to a copied image — needs writeback.
                if not getattr(self, '_native_debugfs_path', None):
                    self._needs_writeback = True

                # A/B partition layout: also write to the partner partition
                ab = getattr(self, '_ab_partitions', None)
                native = getattr(self, '_native_debugfs_path', None)
                if ab and native and len(ab) > 1:
                    primary_dev = self._wsl_img
                    device = self.device_path
                    for alt_part in ab[1:]:
                        alt_dev = device.replace(
                            "/dev/disk", "/dev/rdisk") + f"s{alt_part}"
                        self.log(
                            f"A/B layout: writing same changes to "
                            f"partner partition {device}s{alt_part}...",
                            "info")
                        self._wsl_img = alt_dev
                        try:
                            # Validate the partner is also ext4
                            self._debugfs_run("stats", timeout=30)
                            self._phase_encrypt_standalone()
                            self.log(
                                f"A/B partner {device}s{alt_part} updated.",
                                "success")
                        except (CommandError, PipelineError) as e:
                            self.log(
                                f"Warning: could not update partner "
                                f"partition {device}s{alt_part}: {e}",
                                "info")
                        finally:
                            self._wsl_img = primary_dev
            else:
                self._phase_encrypt_ssd()
                # Windows A/B mirror: when the drive has an A/B
                # partition layout, the firmware can boot from either
                # slot — writing to only one risks losing the change
                # on the next boot.  After the primary slot is
                # updated, re-mount each partner and replay the
                # encrypt phase against it so both slots match.  This
                # sidesteps the "which is active" question entirely —
                # whichever slot the firmware picks, our changes are
                # there.  (macOS already does this via debugfs on the
                # raw partner device just above; this is the Windows
                # equivalent, swapping wsl --mount instead.)
                from .executor import WslExecutor
                if (isinstance(self.executor, WslExecutor)
                        and getattr(self, '_ab_partitions', None)
                        and len(self._ab_partitions) > 1):
                    self._mirror_writes_to_partner_slots_windows()
            self._check_cancel()

            self._succeeded = True
            self.on_phase(cleanup_phase)  # Cleanup
            self._cleanup_ssd()

            self.on_done(True,
                "Asset modification complete!\n\n"
                "The SSD has been updated directly. You can now:\n"
                "1. Safely eject the drive\n"
                "2. Install it back in the pinball machine\n"
                "3. Power on — no USB flashing needed!")

        except PipelineError as e:
            self.log(str(e), "error")
            self.on_phase(cleanup_phase)
            self._cleanup_ssd()
            self.on_done(False, str(e))
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.on_phase(cleanup_phase)
            self._cleanup_ssd()
            self.on_done(False, f"Unexpected error: {e}")

    def _phase_encrypt_ssd(self):
        """Re-encrypt changed files and write directly to mounted SSD.

        Unlike _phase_encrypt_standalone (which uses debugfs on a raw image),
        this writes encrypted files directly to the live-mounted ext4
        filesystem via cp.  System files (from system/ subfolder) are
        written directly without encryption.
        """
        import os
        import re as _re
        import hashlib as _hl
        import base64 as _b64
        from .crypto import encrypt_file, crc32_buf, decrypt_file as _df
        from .filelist import parse_fl_dat, detect_edata_prefix

        # Separate system files from edata files
        system_files = [(r, p) for r, p in self.changed_files
                        if r.startswith("system/")]
        edata_files = [(r, p) for r, p in self.changed_files
                       if not r.startswith("system/")]

        mp = self.mount_point  # e.g. /mnt/wsl/PHYSICALDRIVE3p3

        # Process system files first (plain copy, no encryption)
        if system_files:
            self._write_system_files_ssd(system_files, mp)

        if not edata_files:
            if system_files:
                self.log("Only system files were modified (no encryption needed).",
                         "success")
            return

        if not self.fl_dat_path:
            raise PipelineError("Encrypt",
                f"Found {len(edata_files)} modified asset file(s) that need "
                f"encryption, but no fl_decrypted.dat is available.\n\n"
                f"Decrypt with Graphics/Sounds checked first to generate "
                f"the file list, then try again.")

        self.log("Loading file list...", "info")
        entries = parse_fl_dat(self.fl_dat_path)
        edata_prefix = detect_edata_prefix(entries)
        entry_map = {e.path: e for e in entries}
        self.log(f"Loaded {len(entries)} fl.dat entries.", "info")

        total = len(edata_files)
        ok = 0
        fail = 0

        # Create a temp staging directory inside WSL
        tag = uuid.uuid4().hex[:8]
        staging_dir = f"/var/tmp/jjp_ssd_{tag}"
        self.executor.run(f"mkdir -p '{staging_dir}'", timeout=10)

        self.on_progress(0, total, "Encrypting...")
        self.log(f"TOTAL_FILES={total}", "info")

        try:
            for i, (rel_path, win_path) in enumerate(edata_files):
                self._check_cancel()

                full_path = f"{edata_prefix}{rel_path}"
                entry = entry_map.get(full_path)
                if not entry:
                    self.log(f"[FAIL] {rel_path} (not found in fl.dat)", "error")
                    fail += 1
                    continue

                # Read replacement content
                with open(win_path, 'rb') as f:
                    content = f.read()

                # Auto-convert audio files if format/duration doesn't match
                lower = rel_path.lower()
                if lower.endswith(".wav"):
                    content = self._maybe_convert_audio(
                        content, entry, mp, rel_path)
                elif lower.endswith(".ogg"):
                    content = self._maybe_convert_ogg(
                        content, entry, mp, rel_path)

                # Warn if file size differs from original
                try:
                    orig_path = f"{mp}{entry.path}"
                    orig_enc_size = int(self.executor.run(
                        f"stat -c%s '{orig_path}'", timeout=5).strip())
                    orig_content_size = orig_enc_size - entry.filler_size - 4
                    if orig_content_size > 0 and len(content) != orig_content_size:
                        diff = len(content) - orig_content_size
                        direction = "larger" if diff > 0 else "smaller"
                        self.log(
                            f"  Size: {len(content)} bytes "
                            f"({abs(diff)} bytes {direction} than "
                            f"original {orig_content_size})", "info")
                except Exception:
                    pass

                self.log(f"Processing: {full_path}", "info")
                self.log(f"  filler={entry.filler_size} "
                         f"orig_n2={entry.crc_encrypted} "
                         f"orig_n3={entry.crc_decrypted}", "info")

                # Encrypt with CRC forgery
                try:
                    encrypted = encrypt_file(
                        content, entry.filler_size, entry.path,
                        entry.crc_encrypted, entry.crc_decrypted)
                except Exception as e:
                    self.log(f"[FAIL] {rel_path}: {e}", "error")
                    fail += 1
                    continue

                # Verify CRCs
                n2 = crc32_buf(encrypted)
                re_dec = _df(encrypted, entry.filler_size, entry.path)
                n3 = crc32_buf(re_dec)
                n2_ok = n2 == entry.crc_encrypted
                n3_ok = n3 == entry.crc_decrypted

                self.log(f"  n2 forge: want={entry.crc_encrypted} "
                         f"got={n2} {'OK' if n2_ok else 'FAIL'}", "info")
                self.log(f"  n3 forge: want={entry.crc_decrypted} "
                         f"got={n3} {'OK' if n3_ok else 'FAIL'}", "info")

                if not (n2_ok and n3_ok):
                    self.log(f"[VERIFY FAIL] {rel_path}", "error")
                    fail += 1
                    continue

                # Stage encrypted file, then cp to mounted SSD
                enc_b64 = _b64.b64encode(encrypted).decode()
                staging = f"{staging_dir}/enc_{i:05d}.bin"
                expected_size = len(encrypted)
                dest_path = f"{mp}{entry.path}"
                _step = "init"

                try:
                    # Write encrypted bytes to staging file
                    if len(enc_b64) > 30000:
                        import tempfile
                        _tmp_dir = self.executor.host_tmp_dir()
                        _step = f"tempfile in {_tmp_dir}"
                        with tempfile.NamedTemporaryFile(
                            mode='w', suffix='.b64', delete=False,
                            dir=_tmp_dir,
                        ) as tf:
                            tf.write(enc_b64)
                            tmp_win = tf.name
                        wsl_tmp = self.executor.to_exec_path(tmp_win)
                        _step = f"base64 decode {tmp_win} -> {staging}"
                        try:
                            self.executor.run(
                                f"base64 -d '{wsl_tmp}' > '{staging}'",
                                timeout=60)
                        finally:
                            os.unlink(tmp_win)
                    else:
                        _step = (f"echo base64 ({len(enc_b64)} chars) "
                                 f"-> {staging}")
                        self.executor.run(
                            f"echo '{enc_b64}' | base64 -d > '{staging}'",
                            timeout=30)

                    # Verify staging file size
                    _step = f"stat {staging}"
                    actual_size = int(self.executor.run(
                        f"stat -c%s '{staging}'", timeout=5).strip())
                    if actual_size != expected_size:
                        self.log(
                            f"[FAIL] {rel_path} (staging size mismatch: "
                            f"expected {expected_size}, got {actual_size})",
                            "error")
                        fail += 1
                        continue

                    # Copy encrypted file to mounted SSD filesystem
                    _step = f"cp {staging} -> {dest_path}"
                    self.executor.run(
                        f"cp '{staging}' '{dest_path}'", timeout=120)

                    # Verify written file size
                    _step = f"stat {dest_path}"
                    disk_size = int(self.executor.run(
                        f"stat -c%s '{dest_path}'", timeout=5).strip())
                    if disk_size != expected_size:
                        self.log(
                            f"[FAIL] {rel_path} (written size mismatch: "
                            f"expected {expected_size}, got {disk_size})",
                            "error")
                        fail += 1
                        continue

                    self.log(f"[VERIFY OK] {rel_path}", "success")
                    if hasattr(self, '_file_tree_cb'):
                        self._file_tree_cb(rel_path, "Encrypted OK")
                    ok += 1
                except (CommandError, OSError) as e:
                    self.log(f"[FAIL] {rel_path} (write failed at step "
                             f"'{_step}': {e})", "error")
                    fail += 1

                self.on_progress(i + 1, total, f"ok={ok} fail={fail}")

        finally:
            # Clean up staging directory
            try:
                self.executor.run(f"rm -rf '{staging_dir}'", timeout=30)
            except Exception:
                pass

        # Sync to ensure all writes hit the disk
        try:
            self.executor.run("sync", timeout=30)
        except Exception:
            pass

        self.on_progress(total, total, "Complete")
        summary = f"{ok}/{total} files replaced and verified"
        if fail > 0:
            summary += f" ({fail} FAILED)"
            self.log(summary, "error")
        else:
            summary += " successfully"
            self.log(summary, "success")

        if edata_files:
            self.log("CRC32 forgery: encrypted files match original fl.dat checksums.",
                     "success")

    def _mirror_writes_to_partner_slots_windows(self):
        """Re-run the encrypt phase on each A/B partner slot on Windows.

        Called from ``run()`` after the primary slot's encrypt phase
        succeeds.  For every partner partition in ``_ab_partitions``
        (less the one already written), we ``wsl --unmount`` the
        primary, ``wsl --mount`` the partner, content-verify it has
        ``/jjpe/gen1``, then re-run ``_phase_encrypt_ssd`` against
        its mount point.  Same code, different mount underneath.

        Best-effort: a failure on any partner is logged and skipped
        without aborting — the primary slot is already correct, so
        the user gets *at least* a working machine.  The active-slot
        question is sidestepped entirely; whichever slot the
        firmware boots, our changes are there.
        """
        device = self.device_path
        primary_part = self._part_num
        partners = [p for p in (self._ab_partitions or [])
                    if p != primary_part]
        if not partners:
            return

        self.log(
            f"A/B layout detected — replaying writes on partner "
            f"partition(s): {partners}",
            "info")
        for partner_part in partners:
            try:
                self.log(
                    f"Unmounting slot {self._part_num} to swap to "
                    f"partner slot {partner_part}...",
                    "info")
                self.executor.run_host(
                    f'wsl --unmount "{device}"', timeout=15)
                self._ssd_mounted = False
                self.mount_point = None

                mount_cmd = (
                    f'wsl --mount "{device}" '
                    f'--partition {partner_part} --type ext4')
                rc, stdout, stderr = self.executor.run_host(
                    mount_cmd, timeout=30)

                # Same stale-mount recovery the discovery loop uses:
                # immediately after unmounting the primary slot, WSL
                # can still report the disk/partition as attached
                # ("WSL_E_DISK_ALREADY_MOUNTED").  A `wsl --shutdown`
                # clears the stuck attachment; re-offline the disk so
                # Windows releases its drive-letter hold, then retry.
                # Without this the A/B mirror silently skips slot 5 —
                # and if slot 5 is the active one, the machine boots
                # with none of the changes applied.
                if rc != 0 and "ALREADY_MOUNTED" in (
                        stderr or stdout or "").upper():
                    self.log(
                        "Stale WSL mount detected — restarting WSL...",
                        "info")
                    self.executor.run_host('wsl --shutdown', timeout=30)
                    disk_num = device.rstrip().replace(
                        "\\\\", "\\").split("PHYSICALDRIVE")[-1]
                    if disk_num.isdigit():
                        self.executor.run_host(
                            f'powershell -NoProfile -Command '
                            f'"Set-Disk -Number {disk_num} '
                            f'-IsOffline $true"',
                            timeout=15)
                    rc, stdout, stderr = self.executor.run_host(
                        mount_cmd, timeout=30)

                if rc != 0:
                    self.log(
                        f"Could not mount partner slot "
                        f"{partner_part}: "
                        f"{(stderr or stdout or '').strip()[:200]} "
                        f"— skipping",
                        "info")
                    continue

                try:
                    result = self.executor.run(
                        # Match /mnt/wsl/ only — see the discovery-loop
                        # note above; excludes WSLg's distro root.
                        "findmnt -rn -o TARGET -t ext4 | "
                        "grep '/mnt/wsl/'",
                        timeout=10)
                    mounts = [m.strip() for m in
                              result.strip().split("\n") if m.strip()]
                except CommandError:
                    mounts = []
                if not mounts:
                    self.log(
                        f"Partner slot {partner_part} attached but "
                        f"no WSL mount point appeared — skipping",
                        "info")
                    self.executor.run_host(
                        f'wsl --unmount "{device}"', timeout=15)
                    continue
                partner_mp = mounts[-1]

                # Validate the partner is also a JJP game slot — if
                # it isn't, this isn't really an A/B partner and
                # we'd just corrupt unrelated data.
                try:
                    self.executor.run(
                        f"test -d '{partner_mp}{config.GAME_BASE_PATH}'",
                        timeout=10)
                except CommandError:
                    self.log(
                        f"Partner slot {partner_part} mounted at "
                        f"{partner_mp} but {config.GAME_BASE_PATH} "
                        f"absent — not a valid A/B partner, "
                        f"skipping",
                        "info")
                    self.executor.run_host(
                        f'wsl --unmount "{device}"', timeout=15)
                    continue

                # Replay encrypt on this slot.
                self.mount_point = partner_mp
                self._part_num = partner_part
                self._ssd_mounted = True
                self.log(
                    f"Replaying writes on partner slot "
                    f"{partner_part} ({partner_mp})...",
                    "info")
                self._phase_encrypt_ssd()
                self.log(
                    f"A/B partner slot {partner_part} updated.",
                    "success")
            except (CommandError, PipelineError) as e:
                self.log(
                    f"Warning: A/B mirror to partner slot "
                    f"{partner_part} failed: {e}.  The primary slot "
                    f"is still updated.",
                    "info")
                # Best-effort: try to unmount whatever's currently
                # attached so cleanup can proceed cleanly.
                try:
                    self.executor.run_host(
                        f'wsl --unmount "{device}"', timeout=15)
                except Exception:
                    pass

    def _write_system_files_ssd(self, system_files, mp):
        """Write modified system files directly to the mounted SSD.

        These files are NOT encrypted — they live outside edata/ on the
        filesystem and are not listed in fl.dat, so no CRC forgery is needed.
        Just cp them to the correct paths on the mounted filesystem.
        """
        import os
        import base64 as _b64

        total = len(system_files)
        self.log(f"Writing {total} system file(s) (no encryption)...", "info")
        self.on_progress(0, total, "Writing system files...")

        tag = uuid.uuid4().hex[:8]
        staging_dir = f"/var/tmp/jjp_sys_{tag}"
        self.executor.run(f"mkdir -p '{staging_dir}'", timeout=10)

        ok = 0
        fail = 0

        try:
            for i, (rel_path, win_path) in enumerate(system_files):
                self._check_cancel()

                # Convert system/jjpe/gen1/Game/file -> /jjpe/gen1/Game/file
                fs_path = "/" + rel_path[len("system/"):]
                dest_path = f"{mp}{fs_path}"

                with open(win_path, 'rb') as f:
                    content = f.read()

                self.log(f"  System file: {fs_path} ({len(content)} bytes)",
                         "info")

                staging = f"{staging_dir}/sys_{i:05d}.bin"
                try:
                    enc_b64 = _b64.b64encode(content).decode()
                    if len(enc_b64) > 30000:
                        import tempfile
                        with tempfile.NamedTemporaryFile(
                            mode='w', suffix='.b64', delete=False,
                            dir=self.executor.host_tmp_dir(),
                        ) as tf:
                            tf.write(enc_b64)
                            tmp_win = tf.name
                        wsl_tmp = self.executor.to_exec_path(tmp_win)
                        try:
                            self.executor.run(
                                f"base64 -d '{wsl_tmp}' > '{staging}'",
                                timeout=60)
                        finally:
                            os.unlink(tmp_win)
                    else:
                        self.executor.run(
                            f"echo '{enc_b64}' | base64 -d > '{staging}'",
                            timeout=30)

                    # Copy to mounted SSD
                    self.executor.run(
                        f"cp '{staging}' '{dest_path}'", timeout=120)

                    # Verify
                    disk_size = int(self.executor.run(
                        f"stat -c%s '{dest_path}'", timeout=5).strip())
                    if disk_size != len(content):
                        self.log(
                            f"  [FAIL] {fs_path} (size mismatch: "
                            f"expected {len(content)}, got {disk_size})",
                            "error")
                        fail += 1
                        continue

                    self.log(f"  [OK] {fs_path}", "success")
                    ok += 1
                except (CommandError, OSError) as e:
                    self.log(f"  [FAIL] {fs_path}: {e}", "error")
                    fail += 1

                self.on_progress(i + 1, total, f"ok={ok} fail={fail}")

        finally:
            try:
                self.executor.run(f"rm -rf '{staging_dir}'", timeout=30)
            except Exception:
                pass

        self.on_progress(total, total, "System files complete")
        self.log(f"System files: {ok}/{total} written"
                 f"{f' ({fail} failed)' if fail else ''}",
                 "success" if fail == 0 else "error")

    # Reuse mount/unmount from DirectSSDDecryptPipeline
    _detect_partition = DirectSSDDecryptPipeline._detect_partition
    _discover_partitions = DirectSSDDecryptPipeline._discover_partitions
    _discover_partitions_windows = (
        DirectSSDDecryptPipeline._discover_partitions_windows)
    _discover_partitions_macos = (
        DirectSSDDecryptPipeline._discover_partitions_macos)
    _discover_partitions_linux = (
        DirectSSDDecryptPipeline._discover_partitions_linux)
    _build_partition_candidates = (
        DirectSSDDecryptPipeline._build_partition_candidates)
    _update_ab_partitions_for = (
        DirectSSDDecryptPipeline._update_ab_partitions_for)
    _format_partition_map_for_error = (
        DirectSSDDecryptPipeline._format_partition_map_for_error)
    _wsl_bring_disk_online = (
        DirectSSDDecryptPipeline._wsl_bring_disk_online)
    _diagnostic_dump_boot_partitions_windows = (
        DirectSSDDecryptPipeline._diagnostic_dump_boot_partitions_windows)
    _mount_ssd_windows = DirectSSDDecryptPipeline._mount_ssd_windows
    _mount_ssd = DirectSSDDecryptPipeline._mount_ssd
    _cleanup_ssd = DirectSSDDecryptPipeline._cleanup_ssd
    _debugfs_run = DirectSSDDecryptPipeline._debugfs_run
    _debugfs_run_elevated = DirectSSDDecryptPipeline._debugfs_run_elevated
    _detect_game_via_debugfs = DirectSSDDecryptPipeline._detect_game_via_debugfs


class RestoreToSSDPipeline:
    """Restore a Clonezilla ISO directly to a blank (or existing) SSD.

    Reads the partition table and all partition images from the ISO,
    partitions the target SSD, and writes each partition image via dd.

    Phases: Extract > Partition > Restore > Cleanup
    """

    def __init__(self, iso_path, device_path, log_cb, phase_cb, progress_cb,
                 done_cb):
        self.iso_path = iso_path
        self.device_path = device_path
        self.log = log_cb
        self.on_phase = phase_cb
        self.on_progress = progress_cb
        self.on_done = done_cb
        self.cancelled = False
        self._succeeded = False
        self._iso_mount = None
        self._tmp_dir = None
        self.executor = _install_robust_run_host(create_executor())

    def cancel(self):
        self.cancelled = True

    def _check_cancel(self):
        if self.cancelled:
            raise PipelineError("Restore", "Cancelled by user.")

    def _log_system_diagnostics(self):
        """Log basic system info for debugging."""
        import platform
        self.log(f"Platform: {sys.platform} ({platform.machine()})", "info")
        self.log(f"ISO: {self.iso_path}", "info")
        self.log(f"Target device: {self.device_path}", "info")

    def run(self):
        """Execute the ISO-to-SSD restore pipeline."""
        from .executor import WslExecutor, DockerExecutor, NativeExecutor
        cleanup_phase = len(config.RESTORE_TO_SSD_PHASES) - 1
        try:
            self._log_system_diagnostics()

            # Phase 0: Extract — mount ISO and parse metadata
            self.on_phase(0)
            self._phase_extract_metadata()
            self._check_cancel()

            # Phase 1: Partition — create partition table on SSD
            self.on_phase(1)
            self._phase_partition()
            self._check_cancel()

            # Phase 2: Restore — write each partition image
            self.on_phase(2)
            self._phase_restore_partitions()
            self._check_cancel()

            self._succeeded = True
            self.on_phase(cleanup_phase)
            self._phase_cleanup()
            self.on_done(True,
                f"Restore complete!\n"
                f"The SSD now matches the ISO image and is ready to use.")

        except PipelineError as e:
            self.log(str(e), "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup()
            self.on_done(False, str(e))
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.on_phase(cleanup_phase)
            self._phase_cleanup()
            self.on_done(False, f"Unexpected error: {e}")

    def _phase_extract_metadata(self):
        """Mount the ISO and read partition table + partition image info."""
        from .executor import WslExecutor, DockerExecutor

        self.log("Reading ISO contents...", "info")

        # For WSL, copy ISO to Linux filesystem first (loop mount fails on
        # /mnt/c).  For Docker, the ISO is accessible via bind mount.
        if isinstance(self.executor, WslExecutor):
            self._tmp_dir = f"/var/tmp/jjp_restore_{uuid.uuid4().hex[:8]}"
            self.executor.run(f"mkdir -p '{self._tmp_dir}'", timeout=10)
            wsl_iso = self.executor.to_exec_path(self.iso_path)
            self._local_iso = f"{self._tmp_dir}/source.iso"
            self.log("Copying ISO to WSL filesystem...", "info")
            self.executor.run(
                f"cp '{wsl_iso}' '{self._local_iso}'",
                timeout=config.EXTRACT_TIMEOUT)
        elif isinstance(self.executor, DockerExecutor):
            self._tmp_dir = f"/tmp/jjp_restore_{uuid.uuid4().hex[:8]}"
            # Start Docker with ISO accessible
            self.log("Starting Docker container...", "info")
            cache_dir = self.executor._cache_dir()
            self.executor.start_container([self.iso_path])
            self._local_iso = self.executor.to_exec_path(self.iso_path)
        else:
            # Native Linux
            self._tmp_dir = f"/var/tmp/jjp_restore_{uuid.uuid4().hex[:8]}"
            self.executor.run(f"mkdir -p '{self._tmp_dir}'", timeout=10)
            self._local_iso = self.iso_path

        # Mount the ISO
        self._iso_mount = f"{self._tmp_dir}/iso_mnt"
        self.executor.run(f"mkdir -p '{self._iso_mount}'", timeout=10)
        try:
            self.executor.run(
                f"mount -o loop,ro '{self._local_iso}' '{self._iso_mount}'",
                timeout=config.MOUNT_TIMEOUT)
        except CommandError as e:
            raise PipelineError("Extract",
                f"Failed to mount ISO:\n{e.output}") from e

        partimag = f"{self._iso_mount}{config.PARTIMAG_PATH}"

        # Read partition list
        try:
            parts_raw = self.executor.run(
                f"cat '{partimag}/parts'", timeout=10).strip()
        except CommandError as e:
            raise PipelineError("Extract",
                f"No 'parts' file in ISO — is this a Clonezilla image?\n"
                f"{e.output}") from e

        self._partitions = parts_raw.split()
        self.log(f"Partitions in image: {' '.join(self._partitions)}", "info")

        # Read filesystem types
        self._part_fs = {}
        try:
            devfs = self.executor.run(
                f"cat '{partimag}/dev-fs.list'", timeout=10)
            for line in devfs.strip().splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                fields = line.split()
                if len(fields) >= 2:
                    # /dev/sda1 vfat → sda1: vfat
                    name = fields[0].replace("/dev/", "")
                    self._part_fs[name] = fields[1]
        except CommandError:
            pass
        self.log(f"Filesystems: {self._part_fs}", "info")

        # Read sfdisk partition table
        try:
            self._sfdisk_data = self.executor.run(
                f"cat '{partimag}/sda-pt.sf'", timeout=10)
        except CommandError as e:
            raise PipelineError("Extract",
                f"No partition table (sda-pt.sf) in ISO:\n{e.output}") from e
        self.log("Partition table (sda-pt.sf) loaded.", "info")

        # Catalogue partition image chunks
        self._part_chunks = {}
        for part in self._partitions:
            try:
                chunks_raw = self.executor.run(
                    f"ls -1 '{partimag}/{part}.'*'-ptcl-img.gz.'* 2>/dev/null "
                    f"| sort",
                    timeout=10).strip()
                if chunks_raw:
                    chunks = chunks_raw.splitlines()
                    self._part_chunks[part] = chunks
                    total_size = 0
                    for c in chunks:
                        try:
                            sz = self.executor.run(
                                f"stat -c%s '{c}'", timeout=5).strip()
                            total_size += int(sz)
                        except (CommandError, ValueError):
                            pass
                    self.log(f"  {part}: {len(chunks)} chunk(s), "
                             f"{total_size / (1024**2):.0f} MB compressed",
                             "info")
            except CommandError:
                self.log(f"  {part}: no image chunks found", "info")

        if not self._part_chunks:
            raise PipelineError("Extract",
                "No partition images found in ISO.")

        self.log(f"ISO metadata loaded: {len(self._part_chunks)} partition(s) "
                 f"to restore.", "success")

    def _phase_partition(self):
        """Create the partition table on the target SSD."""
        from .executor import WslExecutor, DockerExecutor, NativeExecutor

        device = self.device_path
        self.log(f"Creating partition table on {device}...", "info")

        if isinstance(self.executor, WslExecutor):
            # Attach disk to WSL
            disk_num = device.rstrip().replace("\\\\", "\\").split(
                "PHYSICALDRIVE")[-1]

            # Take disk offline for WSL access
            if disk_num.isdigit():
                self.executor.run_host('wsl --unmount', timeout=15)
                self.log("Taking disk offline for WSL access...", "info")
                rc, _, err = self.executor.run_host(
                    f'powershell -NoProfile -Command '
                    f'"Set-Disk -Number {disk_num} -IsOffline $true"',
                    timeout=15)
                if rc != 0:
                    self.log(f"Warning: could not take disk offline: {err}",
                             "info")
                self._disk_was_offlined = True

            # Attach raw disk to WSL (no partition, whole disk)
            rc, stdout, stderr = self.executor.run_host(
                f'wsl --mount "{device}" --bare', timeout=30)
            if rc != 0:
                raise PipelineError("Partition",
                    f"Failed to attach disk to WSL:\n{stderr or stdout}")
            self._wsl_mounted_device = device

            # Find the block device in WSL
            wsl_dev = self._find_wsl_block_device(device)
            self._wsl_block_dev = wsl_dev

            # Write partition table via sfdisk
            sfdisk_b64 = base64.b64encode(
                self._sfdisk_data.encode()).decode()
            self.executor.run(
                f"echo '{sfdisk_b64}' | base64 -d | sfdisk '{wsl_dev}'",
                timeout=30)
            # Re-read partition table
            self.executor.run(
                f"partprobe '{wsl_dev}' 2>/dev/null; sleep 1; true",
                timeout=15)
            self.log(f"Partition table written to {wsl_dev}.", "success")

        elif isinstance(self.executor, DockerExecutor):
            # macOS: use diskutil to partition, then sgdisk if available
            # First unmount
            self.executor.run_host(
                f"diskutil unmountDisk {device}", timeout=15)

            # Try sgdisk (from Homebrew e2fsprogs/gptfdisk)
            # Write sfdisk data to a temp file, convert with sfdisk in Docker
            # Actually, we can use sgdisk --load-backup on macOS if available,
            # or use diskutil to partition.

            # Simplest approach: use sfdisk inside Docker if we can pass the
            # raw device.  Docker can't do that on macOS.
            # Alternative: write partition table via dd of the GPT backup.
            # The ISO includes sda-gpt-1st (primary GPT) and sda-gpt-2nd
            # (backup GPT) and sda-mbr.

            self.log("Writing GPT partition table via raw image...", "info")

            # Write MBR (protective MBR, first 512 bytes)
            partimag = f"{self._iso_mount}{config.PARTIMAG_PATH}"
            mbr_path = f"{self._tmp_dir}/sda-mbr"
            gpt1_path = f"{self._tmp_dir}/sda-gpt-1st"
            try:
                self.executor.run(
                    f"cp '{partimag}/sda-mbr' '{mbr_path}'", timeout=10)
                self.executor.run(
                    f"cp '{partimag}/sda-gpt-1st' '{gpt1_path}'", timeout=10)
            except CommandError as e:
                raise PipelineError("Partition",
                    f"MBR/GPT files not found in ISO:\n{e.output}") from e

            # Extract to host filesystem for dd
            cache_dir = self.executor._cache_dir()
            host_mbr = os.path.join(cache_dir, "sda-mbr")
            host_gpt1 = os.path.join(cache_dir, "sda-gpt-1st")

            # Copy from Docker container to host via base64
            mbr_b64 = self.executor.run(
                f"base64 '{mbr_path}'", timeout=10).strip()
            import base64 as _b64
            with open(host_mbr, 'wb') as f:
                f.write(_b64.b64decode(mbr_b64))
            gpt1_b64 = self.executor.run(
                f"base64 '{gpt1_path}'", timeout=10).strip()
            with open(host_gpt1, 'wb') as f:
                f.write(_b64.b64decode(gpt1_b64))

            raw_dev = device.replace("/dev/disk", "/dev/rdisk")

            # Write protective MBR (first 446 bytes only — don't touch
            # partition entries in the MBR gap)
            rc, _, err = self.executor.run_host(
                f"dd if='{host_mbr}' of='{raw_dev}' bs=512 count=1",
                timeout=30)
            if rc != 0:
                raise PipelineError("Partition",
                    f"Failed to write MBR:\n{err}")

            # Write primary GPT (starts at LBA 1 = byte 512)
            gpt_size = os.path.getsize(host_gpt1)
            rc, _, err = self.executor.run_host(
                f"dd if='{host_gpt1}' of='{raw_dev}' bs=512 seek=1 "
                f"count={gpt_size // 512}",
                timeout=30)
            if rc != 0:
                raise PipelineError("Partition",
                    f"Failed to write GPT:\n{err}")

            # Also write backup GPT at the end of the disk
            # Get disk size first
            rc, disk_info, _ = self.executor.run_host(
                f"diskutil info {device}", timeout=10)
            disk_sectors = None
            if rc == 0:
                m = re.search(r'Disk Size:.*\((\d+) Bytes\)', disk_info)
                if m:
                    disk_sectors = int(m.group(1)) // 512

            if disk_sectors:
                try:
                    host_gpt2 = os.path.join(cache_dir, "sda-gpt-2nd")
                    gpt2_path = f"{self._tmp_dir}/sda-gpt-2nd"
                    self.executor.run(
                        f"cp '{partimag}/sda-gpt-2nd' '{gpt2_path}'",
                        timeout=10)
                    gpt2_b64 = self.executor.run(
                        f"base64 '{gpt2_path}'", timeout=10).strip()
                    with open(host_gpt2, 'wb') as f:
                        f.write(_b64.b64decode(gpt2_b64))
                    gpt2_size = os.path.getsize(host_gpt2)
                    backup_lba = disk_sectors - (gpt2_size // 512)
                    rc, _, err = self.executor.run_host(
                        f"dd if='{host_gpt2}' of='{raw_dev}' bs=512 "
                        f"seek={backup_lba} count={gpt2_size // 512}",
                        timeout=30)
                    if rc == 0:
                        self.log("Backup GPT written.", "info")
                except Exception:
                    self.log("Warning: could not write backup GPT.", "info")

            self.log("Partition table written.", "success")

        elif isinstance(self.executor, NativeExecutor):
            # Linux: sfdisk directly
            sfdisk_b64 = base64.b64encode(
                self._sfdisk_data.encode()).decode()
            self.executor.run(
                f"echo '{sfdisk_b64}' | base64 -d | sfdisk '{device}'",
                timeout=30)
            self.executor.run(
                f"partprobe '{device}' 2>/dev/null; sleep 1; true",
                timeout=15)
            self.log(f"Partition table written to {device}.", "success")

    def _find_wsl_block_device(self, win_device):
        """Find the block device path inside WSL for a Windows disk."""
        # wsl --mount --bare makes the disk available at /dev/sdX
        # Find it by looking at recently added block devices
        try:
            result = self.executor.run(
                "lsblk -dpno NAME,SIZE 2>/dev/null | grep -v loop",
                timeout=10)
            # Pick the last non-loop block device (most recently attached)
            devices = [l.split()[0] for l in result.strip().splitlines()
                       if l.strip()]
            if devices:
                dev = devices[-1]
                self.log(f"WSL block device: {dev}", "info")
                return dev
        except CommandError:
            pass
        raise PipelineError("Partition",
            "Could not find the attached disk in WSL.")

    def _phase_restore_partitions(self):
        """Restore each partition image to the SSD."""
        from .executor import WslExecutor, DockerExecutor, NativeExecutor

        total_parts = len(self._part_chunks)
        self.on_progress(0, total_parts, "Restoring partitions...")

        for idx, part in enumerate(self._partitions):
            self._check_cancel()

            if part not in self._part_chunks:
                self.log(f"Skipping {part} (no image).", "info")
                continue

            chunks = self._part_chunks[part]
            # Extract partition number from e.g. "sda3" → 3
            m = re.search(r'(\d+)$', part)
            if not m:
                self.log(f"Skipping {part} (can't parse number).", "info")
                continue
            part_num = int(m.group(1))

            fs_type = self._part_fs.get(part, "ext4")
            self.log(f"Restoring {part} ({fs_type}, "
                     f"{len(chunks)} chunk(s))...", "info")

            if isinstance(self.executor, WslExecutor):
                self._restore_partition_wsl(part, part_num, chunks, fs_type)
            elif isinstance(self.executor, DockerExecutor):
                self._restore_partition_macos(part, part_num, chunks, fs_type)
            elif isinstance(self.executor, NativeExecutor):
                self._restore_partition_linux(part, part_num, chunks, fs_type)

            self.on_progress(idx + 1, total_parts, f"Restored {part}")
            self.log(f"  {part} restored.", "success")

        self.log(f"All {total_parts} partition(s) restored.", "success")

    def _restore_partition_wsl(self, part, part_num, chunks, fs_type):
        """Restore a partition via WSL (partclone.restore or dd)."""
        target_dev = f"{self._wsl_block_dev}{part_num}"
        # Verify partition device exists
        self.executor.run(
            f"test -b '{target_dev}'", timeout=5)

        cat_chunks = " ".join(f"'{c}'" for c in chunks)
        # Use partclone.restore to decompress and write directly
        partclone_type = f"partclone.{fs_type}" if fs_type != "vfat" \
            else "partclone.vfat"
        # Check if the specific partclone variant exists, fall back to
        # partclone.restore (generic)
        try:
            self.executor.run(f"which {partclone_type}", timeout=5)
        except CommandError:
            partclone_type = "partclone.restore"

        cmd = (
            f"cat {cat_chunks} | gunzip -c | "
            f"{partclone_type} -C -s - -o '{target_dev}' 2>&1"
        )
        try:
            for line in self.executor.stream(cmd,
                                             timeout=config.EXTRACT_TIMEOUT):
                self._check_cancel()
                if "Completed:" in line:
                    m = re.search(r'Completed:\s*([\d.]+)%', line)
                    if m:
                        pct = float(m.group(1))
                        self.on_progress(int(pct), 100,
                            f"Restoring {part}: {pct:.0f}%")
        except CommandError as e:
            raise PipelineError("Restore",
                f"Failed to restore {part}:\n{e.output}") from e

    def _restore_partition_macos(self, part, part_num, chunks, fs_type):
        """Restore a partition on macOS via Docker extract + dd."""
        device = self.device_path
        raw_dev = device.replace("/dev/disk", "/dev/rdisk") + f"s{part_num}"

        # Extract partition to raw image inside Docker
        raw_img = f"{self._tmp_dir}/{part}.raw"
        cat_chunks = " ".join(f"'{c}'" for c in chunks)

        # Use partclone.restore inside Docker to decompress to raw image
        cmd = (
            f"cat {cat_chunks} | gunzip -c | "
            f"partclone.restore -C -s - -O '{raw_img}' 2>&1"
        )
        try:
            for line in self.executor.stream(cmd,
                                             timeout=config.EXTRACT_TIMEOUT):
                self._check_cancel()
                if "Completed:" in line:
                    m = re.search(r'Completed:\s*([\d.]+)%', line)
                    if m:
                        pct = float(m.group(1))
                        self.on_progress(int(pct), 100,
                            f"Extracting {part}: {pct:.0f}%")
        except CommandError as e:
            raise PipelineError("Restore",
                f"Failed to extract {part}:\n{e.output}") from e

        # Get the raw image size
        try:
            img_size = int(self.executor.run(
                f"stat -c%s '{raw_img}'", timeout=10).strip())
            self.log(f"  Raw image: {img_size / (1024**2):.0f} MB", "info")
        except (CommandError, ValueError):
            img_size = 0

        # Copy raw image to host cache dir, then dd to SSD
        cache_dir = self.executor._cache_dir()
        host_img = os.path.join(cache_dir, f"{part}.raw")

        # Stream from Docker to host via dd through the bind-mounted cache
        wsl_img = self.executor.to_exec_path(host_img)
        self.executor.run(
            f"cp '{raw_img}' '{wsl_img}'",
            timeout=config.EXTRACT_TIMEOUT)

        # Unmount disk before writing
        self.executor.run_host(
            f"diskutil unmountDisk {device}", timeout=15)

        # dd to the partition
        self.log(f"  Writing {part} to {raw_dev}...", "info")
        rc, stdout, stderr = self.executor.run_host(
            f"dd if='{host_img}' of='{raw_dev}' bs=1m",
            timeout=3600)
        if rc != 0:
            raise PipelineError("Restore",
                f"Failed to write {part} to SSD:\n{stderr or stdout}")

        # Clean up host image
        try:
            os.unlink(host_img)
        except OSError:
            pass

    def _restore_partition_linux(self, part, part_num, chunks, fs_type):
        """Restore a partition on Linux via partclone.restore directly."""
        device = self.device_path
        target_dev = f"{device}{part_num}"

        cat_chunks = " ".join(f"'{c}'" for c in chunks)
        partclone_type = f"partclone.{fs_type}" if fs_type != "vfat" \
            else "partclone.vfat"
        try:
            self.executor.run(f"which {partclone_type}", timeout=5)
        except CommandError:
            partclone_type = "partclone.restore"

        cmd = (
            f"cat {cat_chunks} | gunzip -c | "
            f"{partclone_type} -C -s - -o '{target_dev}' 2>&1"
        )
        try:
            for line in self.executor.stream(cmd,
                                             timeout=config.EXTRACT_TIMEOUT):
                self._check_cancel()
                if "Completed:" in line:
                    m = re.search(r'Completed:\s*([\d.]+)%', line)
                    if m:
                        pct = float(m.group(1))
                        self.on_progress(int(pct), 100,
                            f"Restoring {part}: {pct:.0f}%")
        except CommandError as e:
            raise PipelineError("Restore",
                f"Failed to restore {part}:\n{e.output}") from e

    def _phase_cleanup(self):
        """Unmount ISO and clean up temp files."""
        from .executor import WslExecutor

        self.log("Cleaning up...", "info")

        # Unmount ISO
        if self._iso_mount:
            try:
                self.executor.run(
                    f"umount '{self._iso_mount}' 2>/dev/null; true",
                    timeout=30)
            except CommandError:
                pass

        # Detach disk from WSL
        if isinstance(self.executor, WslExecutor):
            if hasattr(self, '_wsl_mounted_device'):
                self.executor.run_host(
                    f'wsl --unmount "{self._wsl_mounted_device}"',
                    timeout=15)
            if getattr(self, '_disk_was_offlined', False):
                disk_num = self.device_path.rstrip().replace(
                    "\\\\", "\\").split("PHYSICALDRIVE")[-1]
                if disk_num.isdigit():
                    self.executor.run_host(
                        f'powershell -NoProfile -Command '
                        f'"Set-Disk -Number {disk_num} -IsOffline $false"',
                        timeout=15)

        # Stop Docker container
        if hasattr(self.executor, 'stop_container'):
            try:
                self.executor.stop_container()
            except Exception:
                pass

        # Clean up temp directory
        if self._tmp_dir:
            try:
                self.executor.run(
                    f"rm -rf '{self._tmp_dir}' 2>/dev/null; true",
                    timeout=30)
            except CommandError:
                pass
            # Also clean up local ISO copy on WSL
            if hasattr(self, '_local_iso') and '/var/tmp/' in str(self._local_iso):
                try:
                    self.executor.run(
                        f"rm -f '{self._local_iso}' 2>/dev/null; true",
                        timeout=10)
                except CommandError:
                    pass

        self.log("Cleanup complete.", "success")


def export_mod_pack(assets_folder, output_zip, log_cb=None, progress_cb=None):
    """Scan assets folder for modified files and package them into a zip.

    The zip contains:
    - Only files that differ from the baseline .checksums.md5
    - fl_decrypted.dat (needed for CRC forgery when applying the pack)
    - .checksums.md5 (so the recipient can apply further mods on top)

    Returns (num_changed, zip_path) on success, raises PipelineError on failure.
    """
    import hashlib
    import os
    import re
    import zipfile

    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    checksums_file = os.path.join(assets_folder, '.checksums.md5')
    if not os.path.isfile(checksums_file):
        raise PipelineError("Export",
            "No .checksums.md5 found in the assets folder.\n"
            "Run Decrypt first to generate baseline checksums.")

    fl_dat_path = os.path.join(assets_folder, 'fl_decrypted.dat')
    if not os.path.isfile(fl_dat_path):
        raise PipelineError("Export",
            "No fl_decrypted.dat found in the assets folder.\n"
            "Run Decrypt first to generate the file list.")

    # Load saved checksums
    saved = {}
    with open(checksums_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.match(r'^([a-f0-9]{32})\s+\*?(.+)$', line)
            if m:
                filepath = m.group(2)
                if filepath.startswith('./'):
                    filepath = filepath[2:]
                saved[filepath] = m.group(1)

    log(f"Loaded {len(saved)} baseline checksums.", "info")

    # Collect files to scan
    all_files = []
    for root, _dirs, files in os.walk(assets_folder):
        for name in files:
            if name.startswith('.') or name == 'fl_decrypted.dat' or name.endswith('.img'):
                continue
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, assets_folder).replace('\\', '/')
            if rel_path in saved:
                all_files.append((rel_path, full_path))

    total = len(all_files)
    log(f"Checking {total} files for changes...", "info")

    changed = []
    for i, (rel_path, full_path) in enumerate(all_files):
        h = hashlib.md5()
        with open(full_path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(65536), b''):
                h.update(chunk)
        if saved[rel_path] != h.hexdigest():
            changed.append((rel_path, full_path))
            log(f"  Modified: {rel_path}", "info")
        if progress_cb and ((i + 1) % 500 == 0 or i + 1 == total):
            progress_cb(i + 1, total, f"{len(changed)} changed so far")

    if not changed:
        raise PipelineError("Export",
            "No modified files detected.\n"
            "Modify files in the output folder first, then export.")

    log(f"Found {len(changed)} modified file(s). Creating mod pack...", "info")

    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add changed files
        for rel_path, full_path in changed:
            zf.write(full_path, rel_path)

        # Include fl_decrypted.dat and checksums for the recipient
        zf.write(fl_dat_path, 'fl_decrypted.dat')
        zf.write(checksums_file, '.checksums.md5')

    zip_size = os.path.getsize(output_zip)
    size_mb = zip_size / (1024 * 1024)
    log(f"Mod pack saved: {output_zip} ({size_mb:.1f} MB, "
        f"{len(changed)} file(s))", "success")

    return len(changed), output_zip


def import_mod_pack(zip_path, assets_folder, log_cb=None, progress_cb=None):
    """Extract a mod pack ZIP into the assets folder.

    Overwrites files in assets_folder with the contents of the zip.
    Returns the number of files extracted.
    """
    import os
    import zipfile

    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    if not os.path.isfile(zip_path):
        raise PipelineError("Import", f"Mod pack not found: {zip_path}")

    if not os.path.isdir(assets_folder):
        raise PipelineError("Import",
            f"Output folder does not exist:\n{assets_folder}")

    with zipfile.ZipFile(zip_path, 'r') as zf:
        members = [m for m in zf.namelist() if not m.endswith('/')]
        total = len(members)
        if total == 0:
            raise PipelineError("Import", "Mod pack is empty.")

        log(f"Extracting {total} file(s) from mod pack...", "info")

        for i, name in enumerate(members):
            zf.extract(name, assets_folder)
            if progress_cb and ((i + 1) % 100 == 0 or i + 1 == total):
                progress_cb(i + 1, total, name)

    log(f"Imported {total} file(s) into {assets_folder}", "success")
    return total


def _mod_blocking_prereqs(executor, prereq_results):
    """Filter prereq failures down to the ones that block an ISO Write.

    On macOS the whole ISO Write runs inside the Docker container, whose
    image carries its own debugfs (e2fsprogs / e2fsprogs-extra in the
    Dockerfile).  The debugfs entry check_prerequisites reports there is
    the *native* Homebrew binary, which only enables the Direct-SSD
    no-copy path — its absence must not abort an ISO Write.
    """
    from .executor import DockerExecutor
    optional = ({"debugfs"} if isinstance(executor, DockerExecutor)
                else set())
    return [(name, msg) for name, passed, msg in prereq_results
            if not passed and name not in optional]


def check_prerequisites(executor, standalone=False):
    """Check all prerequisites. Returns list of (name, passed, message) tuples."""
    import sys as _sys
    from .executor import WslExecutor, NativeExecutor, DockerExecutor

    results = []

    if isinstance(executor, WslExecutor):
        # Windows: check WSL2 + tools inside WSL
        try:
            executor.run("echo ok", timeout=15)
            results.append(("WSL2", True, "Available"))
        except Exception:
            results.append(("WSL2", False,
                "WSL2 not available. Install from Microsoft Store."))

        try:
            executor.run("which partclone.ext4", timeout=10)
            results.append(("partclone", True, "Available"))
        except Exception:
            results.append(("partclone", False,
                "Not installed. Run: wsl -u root -- apt install partclone"))

        try:
            executor.run("which xorriso", timeout=10)
            results.append(("xorriso", True, "Available"))
        except Exception:
            results.append(("xorriso", False,
                "Not installed. Run: wsl -u root -- apt install xorriso"))

        try:
            executor.run("which debugfs", timeout=10)
            results.append(("debugfs", True, "Available"))
        except Exception:
            results.append(("debugfs", False,
                "Not installed. Run: wsl -u root -- apt install e2fsprogs"))

        try:
            executor.run("which pigz", timeout=10)
            results.append(("pigz", True, "Available"))
        except Exception:
            results.append(("pigz", False,
                "Not installed. Run: wsl -u root -- apt install pigz"))

        try:
            executor.run("which ffmpeg", timeout=10)
            results.append(("ffmpeg", True, "Available"))
        except Exception:
            results.append(("ffmpeg", False,
                "Not installed. Run: wsl -u root -- apt install ffmpeg"))

    elif isinstance(executor, DockerExecutor):
        # macOS: check Docker Desktop
        ok, msg = executor.check_available()
        results.append(("Docker", ok, msg))

        if ok:
            # Check that the image exists or can be built
            try:
                executor.start_container()
                executor.run("echo ok", timeout=15)
                results.append(("partclone", True, "Available (in container)"))
                results.append(("xorriso", True, "Available (in container)"))
                executor.stop_container()
            except Exception as e:
                results.append(("partclone", False, f"Container check failed: {e}"))
                results.append(("xorriso", False, f"Container check failed: {e}"))
                try:
                    executor.stop_container()
                except Exception:
                    pass

        # Native debugfs (Homebrew e2fsprogs) — enables direct SSD access
        native_debugfs = _find_native_debugfs()
        if native_debugfs:
            results.append(("debugfs", True,
                f"Available (native: {native_debugfs})"))
        else:
            results.append(("debugfs", False,
                "Not installed. Run: brew install e2fsprogs\n"
                "  (enables direct SSD access without copying)"))

    elif isinstance(executor, NativeExecutor):
        # Linux: check tools directly
        ok, msg = executor.check_available()
        results.append(("System", ok, msg))

        try:
            executor.run("which partclone.ext4", timeout=10)
            results.append(("partclone", True, "Available"))
        except Exception:
            results.append(("partclone", False,
                "Not installed. Run: sudo apt install partclone"))

        try:
            executor.run("which xorriso", timeout=10)
            results.append(("xorriso", True, "Available"))
        except Exception:
            results.append(("xorriso", False,
                "Not installed. Run: sudo apt install xorriso"))

        try:
            executor.run("which debugfs", timeout=10)
            results.append(("debugfs", True, "Available"))
        except Exception:
            results.append(("debugfs", False,
                "Not installed. Run: sudo apt install e2fsprogs"))

        try:
            executor.run("which pigz", timeout=10)
            results.append(("pigz", True, "Available"))
        except Exception:
            results.append(("pigz", False,
                "Not installed. Run: sudo apt install pigz"))

        try:
            executor.run("which ffmpeg", timeout=10)
            results.append(("ffmpeg", True, "Available"))
        except Exception:
            results.append(("ffmpeg", False,
                "Not installed. Run: sudo apt install ffmpeg"))

    return results
