"""Embedded C sources for the JJP decryptor and stub libraries."""

# Minimal stub C source - just enough for the linker
STUB_C_SOURCE = """\
void __stub_placeholder(void) {}
"""

# The main decryptor C source - based on proven gnr_decrypt.c with modifications:
# 1. Output path from JJP_OUTPUT_DIR env var (default /tmp/jjp_decrypted)
# 2. TOTAL_FILES count emitted after parsing fl.dat
# 3. Progress every 100 files instead of 500
# 4. fl_decrypted.dat saved to output dir
DECRYPT_C_SOURCE = r"""
/*
 * jjp_decrypt.c - Universal JJP game asset decryptor
 *
 * Algorithm:
 * 1. Hook fm_process_filelist, let game parse fl.dat
 * 2. Re-decrypt fl.dat with dongle_decrypt_buffer
 * 3. Parse entries, decrypt each file with set_seeds_for_crypto + LE rand64 XOR
 * 4. Skip filler bytes, write content
 *
 * Addresses are found via dlsym (game-independent).
 */
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <dlfcn.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>

typedef const char* (*fn_path)(void);
typedef void (*fn_set_crypto)(const char *);
typedef uint64_t (*fn_rand64)(void);
typedef void (*fn_dongle_decrypt)(void *buf, unsigned int size);
typedef void (*fn_process_fl)(const char*, const char*);
typedef int (*fn_void_int)(void);
typedef void (*fn_void_void)(void);

static const uint8_t png_magic[]  = {0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A};
static const uint8_t webm_magic[] = {0x1A,0x45,0xDF,0xA3};
static const uint8_t ogg_magic[]  = {'O','g','g','S'};

#define HOOK_SIZE 14
static uint8_t orig_pfl[HOOK_SIZE];
static void *pfl_addr = NULL;
static fn_set_crypto g_set_crypto;
static fn_rand64 g_rand64;
static fn_dongle_decrypt g_dongle_decrypt;

static char g_edata_prefix[256] = "";
static char g_output_dir[4096] = "/tmp/jjp_decrypted";

static void *page_align(void *a) { return (void*)((uintptr_t)a & ~0xFFF); }
static void write_jmp(uint8_t *t, void *d) {
    mprotect(page_align(t), 0x2000, PROT_READ|PROT_WRITE|PROT_EXEC);
    t[0]=0xFF; t[1]=0x25; t[2]=t[3]=t[4]=t[5]=0;
    *(uint64_t*)(t+6) = (uint64_t)d;
    __builtin_ia32_sfence();
}

static void mkdirs(const char *path) {
    char tmp[4096];
    snprintf(tmp, sizeof(tmp), "%s", path);
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') { *p = '\0'; mkdir(tmp, 0755); *p = '/'; }
    }
    mkdir(tmp, 0755);
}

static void do_decrypt(const char *fl_path) {
    fprintf(stderr, "[decrypt] fl.dat path: %s\n", fl_path);

    /* Read output dir from environment */
    const char *env_out = getenv("JJP_OUTPUT_DIR");
    if (env_out && env_out[0])
        snprintf(g_output_dir, sizeof(g_output_dir), "%s", env_out);
    mkdirs(g_output_dir);

    FILE *f = fopen(fl_path, "rb");
    if (!f) {
        fprintf(stderr, "[decrypt] Cannot open fl.dat: %s\n", fl_path);
        syscall(SYS_exit_group, 1);
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc(fsize + 16);
    fread(data, 1, fsize, f);
    fclose(f);

    fprintf(stderr, "[decrypt] Decrypting fl.dat (%ld bytes)...\n", fsize);
    g_dongle_decrypt(data, (unsigned)fsize);

    /* Check if text */
    int printable = 1;
    for (int i = 0; i < 32 && i < fsize; i++) {
        if (data[i] != '\n' && data[i] != '\r' && data[i] != '\t' &&
            (data[i] < 0x20 || data[i] > 0x7e)) { printable = 0; break; }
    }

    if (!printable) {
        fprintf(stderr, "[decrypt] fl.dat decryption FAILED (not text)\n");
        free(data);
        syscall(SYS_exit_group, 1);
    }

    fprintf(stderr, "[decrypt] fl.dat decrypted OK. First line:\n  ");
    char *nl = memchr(data, '\n', fsize);
    if (nl) fwrite(data, 1, nl - (char*)data, stderr);
    fprintf(stderr, "\n");

    /* Count total files */
    int total_files = 0;
    for (long i = 0; i < fsize; i++) {
        if (data[i] == '\n') total_files++;
    }
    fprintf(stderr, "[decrypt] TOTAL_FILES=%d\n", total_files);

    /* Save decrypted fl.dat to output dir */
    {
        char fl_out[4096];
        snprintf(fl_out, sizeof(fl_out), "%s/fl_decrypted.dat", g_output_dir);
        FILE *out = fopen(fl_out, "wb");
        if (out) { fwrite(data, 1, fsize, out); fclose(out); }
    }
    /* Also save to /tmp for the batch phase */
    {
        FILE *out = fopen("/tmp/fl_decrypted.dat", "wb");
        if (out) { fwrite(data, 1, fsize, out); fclose(out); }
    }

    /* Detect edata prefix from first entry */
    {
        char first[4096];
        size_t flen = nl ? (size_t)(nl - (char*)data) : (fsize < 4095 ? fsize : 4095);
        memcpy(first, data, flen);
        first[flen] = '\0';
        char *edata = strstr(first, "/edata/");
        if (edata) {
            size_t plen = (edata - first) + 7;
            memcpy(g_edata_prefix, first, plen);
            g_edata_prefix[plen] = '\0';
            fprintf(stderr, "[decrypt] Detected edata prefix: '%s'\n", g_edata_prefix);
        }
    }

    /* Quick verify on first PNGs */
    fprintf(stderr, "\n[decrypt] === Verification ===\n");
    {
        char *line = (char*)data;
        char *end = (char*)data + fsize;
        int tested = 0;
        while (line < end && tested < 3) {
            char *lnl = memchr(line, '\n', end - line);
            if (!lnl) lnl = end;
            size_t len = lnl - line;
            if (len > 0 && line[len-1] == '\r') len--;

            char entry[4096];
            if (len > 0 && len < sizeof(entry)) {
                memcpy(entry, line, len);
                entry[len] = '\0';

                char *c1 = strrchr(entry, ','); if (!c1) goto next;
                *c1 = '\0';
                char *c2 = strrchr(entry, ','); if (!c2) goto next;
                *c2 = '\0';
                char *c3 = strrchr(entry, ','); if (!c3) goto next;
                *c3 = '\0';
                uint32_t n1 = (uint32_t)atol(c3 + 1);
                char *filepath = entry;

                const char *ext = strrchr(filepath, '.');
                if (ext && strcasecmp(ext, ".png") == 0) {
                    FILE *ef = fopen(filepath, "rb");
                    if (ef) {
                        fseek(ef, 0, SEEK_END);
                        long esize = ftell(ef);
                        fseek(ef, 0, SEEK_SET);
                        uint8_t *edata = malloc(esize);
                        fread(edata, 1, esize, ef);
                        fclose(ef);

                        g_set_crypto(filepath);
                        for (long pos = 0; pos < esize; pos += 8) {
                            uint64_t k = g_rand64();
                            for (int b = 0; b < 8 && pos + b < esize; b++)
                                edata[pos + b] ^= ((k >> (b * 8)) & 0xFF);
                        }

                        if (esize > n1 + 8 && memcmp(edata + n1, png_magic, 8) == 0)
                            fprintf(stderr, "  [OK] %s\n", filepath);
                        else
                            fprintf(stderr, "  [FAIL] %s (filler=%u)\n", filepath, n1);
                        free(edata);
                        tested++;
                    }
                }
            }
            next:
            line = lnl + 1;
        }
    }

    /* Batch decrypt */
    fprintf(stderr, "\n[decrypt] === BATCH DECRYPTION ===\n");
    {
        FILE *fl2 = fopen("/tmp/fl_decrypted.dat", "r");
        if (!fl2) { fprintf(stderr, "Cannot reopen fl\n"); goto done; }

        int total = 0, ok = 0, fail = 0, skip = 0;
        char ln[4096];

        while (fgets(ln, sizeof(ln), fl2)) {
            size_t len = strlen(ln);
            while (len > 0 && (ln[len-1] == '\n' || ln[len-1] == '\r'))
                ln[--len] = '\0';
            if (len == 0) continue;

            char *c1 = strrchr(ln, ','); if (!c1) continue; *c1 = '\0';
            char *c2 = strrchr(ln, ','); if (!c2) continue; *c2 = '\0';
            char *c3 = strrchr(ln, ','); if (!c3) continue; *c3 = '\0';
            uint32_t n1 = (uint32_t)atol(c3 + 1);
            char *fp = ln;

            FILE *ef = fopen(fp, "rb");
            if (!ef) { skip++; total++; continue; }
            fseek(ef, 0, SEEK_END);
            long esize = ftell(ef);
            fseek(ef, 0, SEEK_SET);
            if (esize <= n1) { fclose(ef); skip++; total++; continue; }
            uint8_t *edata = malloc(esize);
            fread(edata, 1, esize, ef);
            fclose(ef);

            g_set_crypto(fp);
            for (long pos = 0; pos < esize; pos += 8) {
                uint64_t k = g_rand64();
                for (int b = 0; b < 8 && pos + b < esize; b++)
                    edata[pos + b] ^= ((k >> (b * 8)) & 0xFF);
            }

            /* Build output path */
            const char *rel = fp;
            if (g_edata_prefix[0] && strncmp(fp, g_edata_prefix, strlen(g_edata_prefix)) == 0)
                rel = fp + strlen(g_edata_prefix);

            char outpath[4096];
            snprintf(outpath, sizeof(outpath), "%s/%s", g_output_dir, rel);

            char dir[4096];
            snprintf(dir, sizeof(dir), "%s", outpath);
            char *sl = strrchr(dir, '/');
            if (sl) { *sl = '\0'; mkdirs(dir); }

            FILE *of = fopen(outpath, "wb");
            if (of) {
                fwrite(edata + n1, 1, esize - n1, of);
                fclose(of);
                ok++;
            } else {
                fail++;
            }
            free(edata);
            total++;
            if (total % 100 == 0)
                fprintf(stderr, "  Progress: %d (ok=%d fail=%d skip=%d)\n",
                        total, ok, fail, skip);
        }
        fclose(fl2);

        fprintf(stderr, "\n=== BATCH COMPLETE ===\n");
        fprintf(stderr, "  Total: %d  OK: %d  Failed: %d  Skipped: %d\n",
                total, ok, fail, skip);
    }

done:
    free(data);
    syscall(SYS_exit_group, 0);
}

typedef int (*fn_al_install)(int, int (*)(void (*)(void)));

int al_install_system(int version, int (*atexit_ptr)(void (*)(void))) {
    signal(SIGPIPE, SIG_IGN);
    void *h = dlopen(NULL, RTLD_NOW);

    fprintf(stderr, "[decrypt] Finding functions...\n");
    g_set_crypto = (fn_set_crypto)dlsym(h, "_Z27jcrypt_set_seeds_for_cryptoPKc");
    g_rand64 = (fn_rand64)dlsym(h, "_Z13jcrypt_rand64v");
    g_dongle_decrypt = (fn_dongle_decrypt)dlsym(h, "_Z21dongle_decrypt_bufferPvj");
    pfl_addr = dlsym(h, "_Z19fm_process_filelistPKcS0_");

    fprintf(stderr, "  set_seeds_for_crypto = %p\n", (void*)g_set_crypto);
    fprintf(stderr, "  rand64 = %p\n", (void*)g_rand64);
    fprintf(stderr, "  dongle_decrypt = %p\n", (void*)g_dongle_decrypt);
    fprintf(stderr, "  fm_process_filelist = %p\n", pfl_addr);

    if (!g_set_crypto || !g_rand64 || !g_dongle_decrypt) {
        fprintf(stderr, "[decrypt] Missing critical crypto functions!\n");
        syscall(SYS_exit_group, 1);
    }
    if (!pfl_addr) {
        fprintf(stderr, "[decrypt] Warning: fm_process_filelist not found (non-critical)\n");
    }

    fprintf(stderr, "[decrypt] All functions found.\n");

    /* The dongle_decrypt_buffer function needs an active HASP session.
     * Search for and call the dongle initialization function to establish
     * the HASP license session before we try to decrypt fl.dat. */
    {
        void *dinit = NULL;
        /* Try common mangled C++ names for dongle init functions */
        const char *init_names[] = {
            "_Z11dongle_initv",           /* dongle_init() */
            "_Z11dongle_initb",           /* dongle_init(bool) */
            "_Z17dongle_initializev",     /* dongle_initialize() */
            "_Z14dongle_connectv",        /* dongle_connect() */
            "_Z12dongle_loginv",          /* dongle_login() */
            "_Z10DongleInitv",            /* DongleInit() */
            "_Z11dongle_initRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE", /* dongle_init(std::string const&) */
            "dongle_init",                /* extern "C" */
            "dongle_initialize",
            NULL
        };
        for (int i = 0; init_names[i]; i++) {
            dinit = dlsym(h, init_names[i]);
            if (dinit) {
                fprintf(stderr, "[decrypt] Found dongle init: %s @ %p\n",
                        init_names[i], dinit);
                break;
            }
        }

        if (dinit) {
            fprintf(stderr, "[decrypt] Calling dongle init...\n");
            /* Try calling as void->int first (most common) */
            int ret = ((fn_void_int)dinit)();
            fprintf(stderr, "[decrypt] Dongle init returned: %d\n", ret);
        } else {
            fprintf(stderr, "[decrypt] WARNING: No dongle init function found!\n");
            fprintf(stderr, "[decrypt] Will attempt decryption anyway...\n");
        }
    }

    /* Find fl.dat from game binary path via /proc/self/exe */
    char exe_path[4096];
    ssize_t elen = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
    if (elen <= 0) {
        fprintf(stderr, "[decrypt] Cannot read /proc/self/exe\n");
        syscall(SYS_exit_group, 1);
    }
    exe_path[elen] = '\0';
    fprintf(stderr, "[decrypt] Game binary: %s\n", exe_path);

    /* Get game directory (dirname of game binary) */
    char *slash = strrchr(exe_path, '/');
    if (slash) *slash = '\0';

    /* Search for fl.dat in common locations */
    char fl_path[4096];
    FILE *fl_test = NULL;
    const char *fl_locations[] = {
        "%s/edata/fl.dat",
        "%s/fl.dat",
        "%s/data/fl.dat",
        NULL
    };
    for (int i = 0; fl_locations[i]; i++) {
        snprintf(fl_path, sizeof(fl_path), fl_locations[i], exe_path);
        fl_test = fopen(fl_path, "rb");
        if (fl_test) { fclose(fl_test); break; }
    }

    if (!fl_test) {
        fprintf(stderr, "[decrypt] Cannot find fl.dat in %s\n", exe_path);
        syscall(SYS_exit_group, 1);
    }

    fprintf(stderr, "[decrypt] Found fl.dat: %s\n", fl_path);
    fprintf(stderr, "[decrypt] Running decryption directly (headless mode).\n");
    do_decrypt(fl_path);

    /* do_decrypt exits via syscall(SYS_exit_group, 0) */
    return 1;
}

__attribute__((constructor))
static void init(void) { signal(SIGPIPE, SIG_IGN); }
"""


# The encryptor C source - re-encrypts replacement assets into the game image.
# Uses CRC32 forgery to make encrypted files match original fl.dat checksums,
# so fl.dat never needs modification. Each file gets 4 suffix bytes appended
# to content (for n3 forgery) and 4 filler bytes adjusted (for n2 forgery).
ENCRYPT_C_SOURCE = r"""
/*
 * jjp_encrypt.c - JJP game asset re-encryptor with CRC32 forgery
 *
 * Algorithm:
 * 1. Hook al_install_system, init dongle session
 * 2. Decrypt fl.dat to get filler counts and original CRC values
 * 3. Read manifest of (relative_path, replacement_path) pairs
 * 4. For each file:
 *    a. N3 forgery: append 4 bytes to content so CRC32 = original n3
 *    b. XOR-encrypt (filler + content + suffix)
 *    c. N2 forgery: adjust 4 filler bytes so CRC32(encrypted) = original n2
 * 5. Restore original fl.dat (no modification needed)
 */
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <dlfcn.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>

typedef void (*fn_set_crypto)(const char *);
typedef uint64_t (*fn_rand64)(void);
typedef void (*fn_dongle_decrypt)(void *buf, unsigned int size);
typedef int (*fn_void_int)(void);
#ifndef RTLD_NEXT
#define RTLD_NEXT ((void *) -1L)
#endif

static fn_set_crypto g_set_crypto;
static fn_rand64 g_rand64;
static fn_dongle_decrypt g_dongle_decrypt;

static char g_edata_prefix[256] = "";
static char g_fl_path[4096] = "";

/* ---- CRC-32 (ISO 3309 / ITU-T V.42, same as zlib/gzip/PNG) ---- */
static uint32_t crc32_tab[256];
static void crc32_init(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int j = 0; j < 8; j++)
            c = (c >> 1) ^ (c & 1 ? 0xEDB88320u : 0);
        crc32_tab[i] = c;
    }
}
static uint32_t crc32_buf(const void *data, long len) {
    uint32_t crc = 0xFFFFFFFF;
    const uint8_t *p = (const uint8_t *)data;
    for (long i = 0; i < len; i++)
        crc = (crc >> 8) ^ crc32_tab[(crc ^ p[i]) & 0xFF];
    return crc ^ 0xFFFFFFFF;
}

/* CRC32 partial - returns INTERNAL state (not XOR-finalized) */
static uint32_t crc32_partial(const void *data, long len) {
    uint32_t crc = 0xFFFFFFFF;
    const uint8_t *p = (const uint8_t *)data;
    for (long i = 0; i < len; i++)
        crc = (crc >> 8) ^ crc32_tab[(crc ^ p[i]) & 0xFF];
    return crc;  /* NOT finalized */
}

/* CRC32 reverse lookup: rev[table[i]>>24] = i */
static uint8_t crc32_rev[256];
static void crc32_rev_init(void) {
    for (int i = 0; i < 256; i++)
        crc32_rev[crc32_tab[i] >> 24] = (uint8_t)i;
}

/* Reverse one CRC32 step given state_after and the byte processed */
static uint32_t crc32_unstep(uint32_t sa, uint8_t byte) {
    uint8_t idx = crc32_rev[sa >> 24];
    return ((sa ^ crc32_tab[idx]) << 8) | (idx ^ byte);
}

/* Reverse CRC32 through a buffer (last byte to first).
 * Given internal state AFTER all bytes, returns state BEFORE first byte. */
static uint32_t crc32_reverse(uint32_t sa, const uint8_t *d, long len) {
    for (long i = len - 1; i >= 0; i--)
        sa = crc32_unstep(sa, d[i]);
    return sa;
}

/* Find 4 bytes transforming CRC32 internal state `start` to `target`.
 * Meet-in-the-middle: forward 2 bytes, backward 2 bytes, match. */
static int crc32_forge_4bytes(uint32_t start, uint32_t target,
                              uint8_t out[4]) {
    #define HT_BITS 17
    #define HT_SIZE (1 << HT_BITS)
    #define HT_MASK (HT_SIZE - 1)
    typedef struct { uint32_t key; uint8_t b0, b1, used; } ht_slot;
    ht_slot *ht = calloc(HT_SIZE, sizeof(ht_slot));

    /* Forward: enumerate (b0, b1) -> s2, store in hash table */
    for (int b0 = 0; b0 < 256; b0++) {
        uint32_t s1 = (start >> 8) ^
                       crc32_tab[(start ^ (uint8_t)b0) & 0xFF];
        for (int b1 = 0; b1 < 256; b1++) {
            uint32_t s2 = (s1 >> 8) ^
                           crc32_tab[(s1 ^ (uint8_t)b1) & 0xFF];
            uint32_t h = (s2 * 2654435761u) >> (32 - HT_BITS);
            while (ht[h & HT_MASK].used)
                h++;
            ht[h & HT_MASK].key = s2;
            ht[h & HT_MASK].b0 = (uint8_t)b0;
            ht[h & HT_MASK].b1 = (uint8_t)b1;
            ht[h & HT_MASK].used = 1;
        }
    }

    /* Backward: reverse 2 steps from target, probe hash table */
    int found = 0;
    uint8_t idx3 = crc32_rev[target >> 24];
    uint32_t s3_hi = (target ^ crc32_tab[idx3]) << 8;

    for (int s3lo = 0; s3lo < 256 && !found; s3lo++) {
        uint32_t s3 = s3_hi | (uint32_t)s3lo;
        uint8_t idx2 = crc32_rev[s3 >> 24];
        uint32_t s2_hi = (s3 ^ crc32_tab[idx2]) << 8;

        for (int s2lo = 0; s2lo < 256 && !found; s2lo++) {
            uint32_t s2 = s2_hi | (uint32_t)s2lo;
            uint32_t h = (s2 * 2654435761u) >> (32 - HT_BITS);
            while (1) {
                uint32_t slot = h & HT_MASK;
                if (!ht[slot].used) break;
                if (ht[slot].key == s2) {
                    out[0] = ht[slot].b0;
                    out[1] = ht[slot].b1;
                    out[2] = (uint8_t)(s2lo ^ idx2);
                    out[3] = (uint8_t)(s3lo ^ idx3);
                    found = 1;
                    break;
                }
                h++;
            }
        }
    }

    free(ht);
    return found;
    #undef HT_BITS
    #undef HT_SIZE
    #undef HT_MASK
}

/* ---- fl.dat entry ---- */
typedef struct fl_entry {
    char path[4096];
    uint32_t n1;      /* filler size */
    uint32_t n2;      /* CRC32 of encrypted file on disk (original) */
    uint32_t n3;      /* CRC32 of decrypted content (original) */
    struct fl_entry *next;
} fl_entry;

static void do_encrypt(const char *fl_path) {
    fprintf(stderr, "[encrypt] fl.dat path: %s\n", fl_path);
    strncpy(g_fl_path, fl_path, sizeof(g_fl_path) - 1);

    crc32_init();
    crc32_rev_init();

    /* Read original encrypted fl.dat (keep a copy for restoration) */
    FILE *f = fopen(fl_path, "rb");
    if (!f) {
        fprintf(stderr, "[encrypt] Cannot open fl.dat: %s\n", fl_path);
        syscall(SYS_exit_group, 1);
    }
    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *fl_orig_enc = malloc(fsize + 16);
    fread(fl_orig_enc, 1, fsize, f);
    fclose(f);

    /* Make a copy for decryption (keep orig_enc intact) */
    uint8_t *fldata = malloc(fsize + 16);
    memcpy(fldata, fl_orig_enc, fsize);
    fldata[fsize] = '\0';  /* null-terminate for safe string ops */

    fprintf(stderr, "[encrypt] Decrypting fl.dat (%ld bytes)...\n", fsize);
    g_dongle_decrypt(fldata, (unsigned)fsize);

    /* Check if decryption produced text */
    int printable = 1;
    for (int i = 0; i < 32 && i < fsize; i++) {
        if (fldata[i] != '\n' && fldata[i] != '\r' && fldata[i] != '\t' &&
            (fldata[i] < 0x20 || fldata[i] > 0x7e)) { printable = 0; break; }
    }
    if (!printable) {
        fprintf(stderr, "[encrypt] fl.dat decryption FAILED (not text)\n");
        free(fldata); free(fl_orig_enc);
        syscall(SYS_exit_group, 1);
    }
    fprintf(stderr, "[encrypt] fl.dat decrypted OK.\n");

    /* Detect edata prefix from first entry */
    {
        char *nl = memchr(fldata, '\n', fsize);
        char first[4096];
        size_t flen = nl ? (size_t)(nl - (char*)fldata) : (fsize < 4095 ? fsize : 4095);
        memcpy(first, fldata, flen);
        first[flen] = '\0';
        char *edata = strstr(first, "/edata/");
        if (edata) {
            size_t plen = (edata - first) + 7;
            memcpy(g_edata_prefix, first, plen);
            g_edata_prefix[plen] = '\0';
            fprintf(stderr, "[encrypt] Detected edata prefix: '%s'\n", g_edata_prefix);
        }
    }

    /* Parse fl.dat into lookup list (now with n2/n3) */
    fl_entry *fl_head = NULL;
    int fl_count = 0;
    {
        char *line = (char*)fldata;
        char *end = (char*)fldata + fsize;
        while (line < end) {
            char *nl = memchr(line, '\n', end - line);
            if (!nl) nl = end;
            size_t len = nl - line;
            if (len > 0 && line[len-1] == '\r') len--;
            if (len > 0 && len < 4096) {
                char entry[4096];
                memcpy(entry, line, len);
                entry[len] = '\0';
                char *c1 = strrchr(entry, ','); if (!c1) goto next;
                *c1 = '\0';
                char *c2 = strrchr(entry, ','); if (!c2) goto next;
                *c2 = '\0';
                char *c3 = strrchr(entry, ','); if (!c3) goto next;
                *c3 = '\0';
                uint32_t n1 = (uint32_t)atol(c3 + 1);
                uint32_t n2 = (uint32_t)strtoul(c2 + 1, NULL, 10);
                uint32_t n3 = (uint32_t)strtoul(c1 + 1, NULL, 10);
                fl_entry *e = calloc(1, sizeof(fl_entry));
                strncpy(e->path, entry, 4095);
                e->path[4095] = '\0';
                e->n1 = n1;
                e->n2 = n2;
                e->n3 = n3;
                e->next = fl_head;
                fl_head = e;
                fl_count++;
            }
            next:
            line = nl + 1;
        }
    }
    fprintf(stderr, "[encrypt] Parsed %d entries from fl.dat\n", fl_count);

    /* Read manifest file */
    const char *manifest_path = getenv("JJP_MANIFEST");
    if (!manifest_path || !manifest_path[0])
        manifest_path = "/tmp/jjp_manifest.txt";

    FILE *mf = fopen(manifest_path, "r");
    if (!mf) {
        fprintf(stderr, "[encrypt] Cannot open manifest: %s\n", manifest_path);
        syscall(SYS_exit_group, 1);
    }

    /* Count entries */
    int total = 0;
    char mline[8192];
    while (fgets(mline, sizeof(mline), mf)) {
        size_t len = strlen(mline);
        while (len > 0 && (mline[len-1] == '\n' || mline[len-1] == '\r'))
            mline[--len] = '\0';
        if (len > 0) total++;
    }
    fseek(mf, 0, SEEK_SET);
    fprintf(stderr, "[encrypt] TOTAL_FILES=%d\n", total);

    int ok = 0, fail = 0, processed = 0;

    while (fgets(mline, sizeof(mline), mf)) {
        size_t len = strlen(mline);
        while (len > 0 && (mline[len-1] == '\n' || mline[len-1] == '\r'))
            mline[--len] = '\0';
        if (len == 0) continue;

        /* Parse: game_relative_path\treplacement_path */
        char *tab = strchr(mline, '\t');
        if (!tab) {
            fprintf(stderr, "[encrypt] [FAIL] Bad manifest line: %s\n", mline);
            fail++; processed++; continue;
        }
        *tab = '\0';
        char *rel_path = mline;
        char *repl_path = tab + 1;

        /* Construct full game path */
        char full_path[4096];
        snprintf(full_path, sizeof(full_path), "%s%s", g_edata_prefix, rel_path);

        fprintf(stderr, "[encrypt] Processing: %s\n", full_path);

        /* Look up filler count in fl.dat */
        uint32_t n1 = 0;
        int found = 0;
        for (fl_entry *e = fl_head; e; e = e->next) {
            if (strcmp(e->path, full_path) == 0) {
                n1 = e->n1; found = 1; break;
            }
        }
        /* Fallback: try path as-is (might already be absolute) */
        if (!found) {
            for (fl_entry *e = fl_head; e; e = e->next) {
                if (strcmp(e->path, rel_path) == 0) {
                    snprintf(full_path, sizeof(full_path), "%s", rel_path);
                    n1 = e->n1; found = 1; break;
                }
            }
        }
        if (!found) {
            fprintf(stderr, "[encrypt] [FAIL] %s (not found in fl.dat)\n", rel_path);
            fail++; processed++; continue;
        }

        /* Read replacement file */
        FILE *rf = fopen(repl_path, "rb");
        if (!rf) {
            fprintf(stderr, "[encrypt] [FAIL] %s (cannot read: %s)\n",
                    rel_path, repl_path);
            fail++; processed++; continue;
        }
        fseek(rf, 0, SEEK_END);
        long rsize = ftell(rf);
        fseek(rf, 0, SEEK_SET);
        uint8_t *rdata = malloc(rsize);
        fread(rdata, 1, rsize, rf);
        fclose(rf);

        /* Look up original CRC values from fl.dat */
        uint32_t orig_n2 = 0, orig_n3 = 0;
        for (fl_entry *e = fl_head; e; e = e->next) {
            if (strcmp(e->path, full_path) == 0) {
                orig_n2 = e->n2;
                orig_n3 = e->n3;
                break;
            }
        }
        fprintf(stderr, "[encrypt]   filler=%u orig_n2=%u orig_n3=%u\n",
                n1, orig_n2, orig_n3);

        /* === N3 FORGERY: append 4 bytes so CRC32(content+4) = orig_n3 === */
        uint8_t n3_suffix[4] = {0};
        {
            uint32_t state = crc32_partial(rdata, rsize);
            uint32_t target = orig_n3 ^ 0xFFFFFFFF;
            if (!crc32_forge_4bytes(state, target, n3_suffix)) {
                fprintf(stderr, "[encrypt] [FAIL] %s (n3 forge failed)\n",
                        rel_path);
                free(rdata); fail++; processed++; continue;
            }
        }
        long content_size = rsize + 4;

        /* Verify n3 forge */
        {
            uint32_t s = crc32_partial(rdata, rsize);
            for (int i = 0; i < 4; i++)
                s = (s >> 8) ^ crc32_tab[(s ^ n3_suffix[i]) & 0xFF];
            uint32_t check = s ^ 0xFFFFFFFF;
            fprintf(stderr, "[encrypt]   n3 forge: want=%u got=%u %s\n",
                    orig_n3, check, check == orig_n3 ? "OK" : "FAIL");
            if (check != orig_n3) {
                fprintf(stderr, "[encrypt] [FAIL] %s (n3 forge verify)\n",
                        rel_path);
                free(rdata); fail++; processed++; continue;
            }
        }

        /* Build buffer: zero filler + content + n3_suffix */
        long total_size = (long)n1 + content_size;
        uint8_t *buf = calloc(1, total_size);
        memcpy(buf + n1, rdata, rsize);
        memcpy(buf + n1 + rsize, n3_suffix, 4);

        /* XOR-encrypt */
        g_set_crypto(full_path);
        for (long pos = 0; pos < total_size; pos += 8) {
            uint64_t k = g_rand64();
            for (int b = 0; b < 8 && pos + b < total_size; b++)
                buf[pos + b] ^= ((k >> (b * 8)) & 0xFF);
        }
        /* buf is now the encrypted file */

        /* === N2 FORGERY: adjust 4 encrypted filler bytes === */
        if (n1 >= 4) {
            long fp = (long)n1 - 4;  /* forge at [n1-4 .. n1-1] */

            /* CRC state after encrypted[0..fp-1] */
            uint32_t state_A = (fp > 0) ?
                crc32_partial(buf, fp) : 0xFFFFFFFF;

            /* CRC state before encrypted[n1..end] by reversing
             * from target through the content portion */
            uint32_t target_final = orig_n2 ^ 0xFFFFFFFF;
            uint32_t state_B = crc32_reverse(
                target_final, buf + n1, total_size - n1);

            uint8_t forge_enc[4];
            if (crc32_forge_4bytes(state_A, state_B, forge_enc)) {
                buf[fp+0] = forge_enc[0];
                buf[fp+1] = forge_enc[1];
                buf[fp+2] = forge_enc[2];
                buf[fp+3] = forge_enc[3];

                uint32_t check = crc32_buf(buf, total_size);
                fprintf(stderr,
                    "[encrypt]   n2 forge: want=%u got=%u %s\n",
                    orig_n2, check,
                    check == orig_n2 ? "OK" : "FAIL");
            } else {
                fprintf(stderr,
                    "[encrypt] [WARN] n2 forge failed for %s\n",
                    rel_path);
            }
        } else {
            fprintf(stderr,
                "[encrypt] [WARN] filler=%u < 4, n2 forge skipped\n",
                n1);
        }

        /* Write encrypted data over original file */
        FILE *of = fopen(full_path, "wb");
        if (!of) {
            fprintf(stderr, "[encrypt] [FAIL] %s (cannot write)\n",
                    rel_path);
            free(buf); free(rdata);
            fail++; processed++; continue;
        }
        fwrite(buf, 1, total_size, of);
        fclose(of);

        /* === Round-trip verification === */
        FILE *vf = fopen(full_path, "rb");
        if (!vf) {
            fprintf(stderr, "[encrypt] [FAIL] %s (re-read)\n", rel_path);
            free(buf); free(rdata);
            fail++; processed++; continue;
        }
        fseek(vf, 0, SEEK_END);
        long vsize = ftell(vf);
        fseek(vf, 0, SEEK_SET);
        uint8_t *vdata = malloc(vsize);
        fread(vdata, 1, vsize, vf);
        fclose(vf);

        /* Verify n2 on disk */
        uint32_t disk_n2 = crc32_buf(vdata, vsize);

        /* Decrypt */
        g_set_crypto(full_path);
        for (long pos = 0; pos < vsize; pos += 8) {
            uint64_t k = g_rand64();
            for (int b = 0; b < 8 && pos + b < vsize; b++)
                vdata[pos + b] ^= ((k >> (b * 8)) & 0xFF);
        }

        /* Verify n3 (content after filler) */
        uint32_t disk_n3 = crc32_buf(vdata + n1, vsize - n1);

        int v_ok = (disk_n2 == orig_n2 && disk_n3 == orig_n3);
        fprintf(stderr, "[encrypt] [%s] %s n2=%u(%s) n3=%u(%s)\n",
                v_ok ? "VERIFY OK" : "VERIFY FAIL", rel_path,
                disk_n2, disk_n2 == orig_n2 ? "match" : "MISMATCH",
                disk_n3, disk_n3 == orig_n3 ? "match" : "MISMATCH");

        if (v_ok) ok++;
        else fail++;

        free(vdata);
        free(buf);
        free(rdata);
        processed++;
        fprintf(stderr, "  Progress: %d (ok=%d fail=%d)\n",
                processed, ok, fail);
    }
    fclose(mf);

    fprintf(stderr, "\n=== ENCRYPT COMPLETE ===\n");
    fprintf(stderr, "  Total: %d  OK: %d  Failed: %d\n", processed, ok, fail);

    /* === Diagnostic: verify unmodified files still match fl.dat CRCs ===
     * This detects if the ext4 pipeline (mount/journal/e2fsck) altered
     * any files we didn't touch. */
    fprintf(stderr, "\n[encrypt] === VERIFYING UNMODIFIED FILES ===\n");
    {
        int samp = 0, samp_ok = 0, samp_fail = 0;
        int stride = fl_count > 20 ? fl_count / 20 : 1;
        int idx = 0;
        for (fl_entry *e = fl_head; e && samp < 20; e = e->next) {
            /* Skip our modified files (check manifest) */
            int is_modified = 0;
            FILE *mfv = fopen(manifest_path, "r");
            if (mfv) {
                char ml[8192];
                while (fgets(ml, sizeof(ml), mfv)) {
                    char *t = strchr(ml, '\t');
                    if (t) *t = '\0';
                    size_t mlen = strlen(ml);
                    while (mlen > 0 && (ml[mlen-1]=='\n' ||
                           ml[mlen-1]=='\r')) ml[--mlen]='\0';
                    char fp2[4096];
                    snprintf(fp2, sizeof(fp2), "%s%s",
                             g_edata_prefix, ml);
                    if (strcmp(fp2, e->path) == 0) {
                        is_modified = 1; break;
                    }
                }
                fclose(mfv);
            }
            if (is_modified) { idx++; continue; }

            /* Sample every stride-th entry */
            if (idx++ % stride != 0) continue;

            FILE *ef = fopen(e->path, "rb");
            if (!ef) continue;
            fseek(ef, 0, SEEK_END);
            long esize = ftell(ef);
            fseek(ef, 0, SEEK_SET);
            uint8_t *edata = malloc(esize);
            fread(edata, 1, esize, ef);
            fclose(ef);

            uint32_t check_n2 = crc32_buf(edata, esize);
            free(edata);

            if (check_n2 != e->n2) {
                fprintf(stderr,
                    "[verify] MISMATCH %s: n2 want=%u got=%u\n",
                    e->path, e->n2, check_n2);
                samp_fail++;
            } else {
                samp_ok++;
            }
            samp++;
        }
        fprintf(stderr, "[verify] Sampled %d unmodified files: "
                "%d OK, %d FAIL\n", samp, samp_ok, samp_fail);
    }

    /* CRC forgery mode: fl.dat is NOT modified.
     * Each file's encrypted output was forged to match the original
     * n2/n3 values in fl.dat. Just restore the original fl.dat. */
    fprintf(stderr, "\n[encrypt] Restoring original fl.dat "
            "(CRC forgery - no modification needed).\n");
    {
        FILE *ff = fopen(g_fl_path, "wb");
        if (ff) {
            fwrite(fl_orig_enc, 1, fsize, ff);
            fclose(ff);
            fprintf(stderr, "[encrypt] Original fl.dat restored "
                    "(%ld bytes).\n", (long)fsize);
        }
    }

    /* Free fl entries */
    while (fl_head) {
        fl_entry *tmp = fl_head;
        fl_head = fl_head->next;
        free(tmp);
    }
    free(fldata);
    free(fl_orig_enc);

    fprintf(stderr, "\n=== ALL DONE ===\n");
    fprintf(stderr, "  Total: %d  OK: %d  Failed: %d\n", processed, ok, fail);
    syscall(SYS_exit_group, fail > 0 ? 1 : 0);
}

typedef int (*fn_al_install)(int, int (*)(void (*)(void)));

int al_install_system(int version, int (*atexit_ptr)(void (*)(void))) {
    signal(SIGPIPE, SIG_IGN);
    void *h = dlopen(NULL, RTLD_NOW);

    fprintf(stderr, "[encrypt] Finding functions...\n");
    g_set_crypto = (fn_set_crypto)dlsym(h, "_Z27jcrypt_set_seeds_for_cryptoPKc");
    g_rand64 = (fn_rand64)dlsym(h, "_Z13jcrypt_rand64v");
    g_dongle_decrypt = (fn_dongle_decrypt)dlsym(h, "_Z21dongle_decrypt_bufferPvj");

    fprintf(stderr, "  set_seeds_for_crypto = %p\n", (void*)g_set_crypto);
    fprintf(stderr, "  rand64 = %p\n", (void*)g_rand64);
    fprintf(stderr, "  dongle_decrypt = %p\n", (void*)g_dongle_decrypt);

    if (!g_set_crypto || !g_rand64 || !g_dongle_decrypt) {
        fprintf(stderr, "[encrypt] Missing critical crypto functions!\n");
        syscall(SYS_exit_group, 1);
    }
    fprintf(stderr, "[encrypt] All functions found.\n");

    /* Initialize HASP dongle session */
    {
        void *dinit = NULL;
        const char *init_names[] = {
            "_Z11dongle_initv",
            "_Z11dongle_initb",
            "_Z17dongle_initializev",
            "_Z14dongle_connectv",
            "_Z12dongle_loginv",
            "_Z10DongleInitv",
            "_Z11dongle_initRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE",
            "dongle_init",
            "dongle_initialize",
            NULL
        };
        for (int i = 0; init_names[i]; i++) {
            dinit = dlsym(h, init_names[i]);
            if (dinit) {
                fprintf(stderr, "[encrypt] Found dongle init: %s @ %p\n",
                        init_names[i], dinit);
                break;
            }
        }
        if (dinit) {
            fprintf(stderr, "[encrypt] Calling dongle init...\n");
            int ret = ((fn_void_int)dinit)();
            fprintf(stderr, "[encrypt] Dongle init returned: %d\n", ret);
        } else {
            fprintf(stderr, "[encrypt] WARNING: No dongle init function found!\n");
            fprintf(stderr, "[encrypt] Will attempt anyway...\n");
        }
    }

    /* Find fl.dat */
    char exe_path[4096];
    ssize_t elen = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
    if (elen <= 0) {
        fprintf(stderr, "[encrypt] Cannot read /proc/self/exe\n");
        syscall(SYS_exit_group, 1);
    }
    exe_path[elen] = '\0';
    fprintf(stderr, "[encrypt] Game binary: %s\n", exe_path);

    char *slash = strrchr(exe_path, '/');
    if (slash) *slash = '\0';

    char fl_path[4096];
    FILE *fl_test = NULL;
    const char *fl_locations[] = {
        "%s/edata/fl.dat", "%s/fl.dat", "%s/data/fl.dat", NULL
    };
    for (int i = 0; fl_locations[i]; i++) {
        snprintf(fl_path, sizeof(fl_path), fl_locations[i], exe_path);
        fl_test = fopen(fl_path, "rb");
        if (fl_test) { fclose(fl_test); break; }
    }
    if (!fl_test) {
        fprintf(stderr, "[encrypt] Cannot find fl.dat in %s\n", exe_path);
        syscall(SYS_exit_group, 1);
    }

    fprintf(stderr, "[encrypt] Found fl.dat: %s\n", fl_path);
    fprintf(stderr, "[encrypt] Running encryption.\n");
    do_encrypt(fl_path);

    return 1;
}

__attribute__((constructor))
static void init(void) { signal(SIGPIPE, SIG_IGN); }
"""
