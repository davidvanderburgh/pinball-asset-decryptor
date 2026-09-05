/* log.c - see log.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include "log.h"

/* The file is bounded two ways so a card can never fill up with menu logs:
 *   - one run, one file: sel_log_open() moves an existing PATH to PATH.1 and
 *     starts PATH afresh, so at most two runs' worth ever exist;
 *   - one run writes at most LOG_CAP_BYTES (PAD_LOG_CAP=<bytes> for the
 *     tests); past that one closing line says so and the file stops while
 *     stderr goes on.  A boot logs ~8 KB; a menu left idle for a week would
 *     stay under the cap since the perf line backs off to one a minute. */
#define LOG_CAP_BYTES (1 << 20)

static FILE *g_logf;
static long long g_t0 = -1;
static long g_cap = LOG_CAP_BYTES, g_bytes;
static int g_capped;

long long sel_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000;
}

void sel_sleep_ms(long ms)
{
    struct timespec ts;
    if (ms <= 0) return;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (ms % 1000) * 1000000L;
    while (nanosleep(&ts, &ts) < 0 && errno == EINTR)
        ;
}

int sel_log_open(const char *path)
{
    char prev[4096];
    const char *cap = getenv("PAD_LOG_CAP");
    if (g_t0 < 0) g_t0 = sel_now_ms();
    if (!path || !*path) return 0;
    if (cap && atol(cap) > 0) g_cap = atol(cap);
    /* the previous run's file becomes PATH.1 (a missing one is no error) */
    if (snprintf(prev, sizeof prev, "%s.1", path) < (int)sizeof prev)
        rename(path, prev);
    g_logf = fopen(path, "w");
    if (!g_logf) {
        fprintf(stderr, "codeselect: cannot open log %s: %s\n", path, strerror(errno));
        return -1;
    }
    setvbuf(g_logf, NULL, _IOLBF, 0);
    g_bytes = 0;
    g_capped = 0;
    return 0;
}

void sel_log_close(void)
{
    if (g_logf) fclose(g_logf);
    g_logf = NULL;
}

static void stamp(char *buf, int n)
{
    long long t;
    if (g_t0 < 0) g_t0 = sel_now_ms();
    t = sel_now_ms() - g_t0;
    snprintf(buf, n, "%5lld.%03lld", t / 1000, t % 1000);
}

static void vline(FILE *f, const char *pfx, const char *fmt, va_list ap)
{
    char ts[32];
    stamp(ts, sizeof ts);
    if (pfx) fputs(pfx, f);
    else { fputs(ts, f); fputc(' ', f); }
    vfprintf(f, fmt, ap);
    fputc('\n', f);
    fflush(f);
}

/* one line into the log file: "<stamp> [tag ]<line>", counted against the
 * cap; the first line past it is replaced by the closing notice */
static void file_line(const char *tag, const char *fmt, va_list ap)
{
    char ts[32];
    int n;
    if (!g_logf || g_capped) return;
    if (g_bytes >= g_cap) {
        stamp(ts, sizeof ts);
        fprintf(g_logf, "%s log: %ld KB this run: the file stops here (stderr goes on)\n",
                ts, g_bytes >> 10);
        fflush(g_logf);
        g_capped = 1;
        return;
    }
    stamp(ts, sizeof ts);
    n = fprintf(g_logf, "%s %s", ts, tag ? tag : "");
    n += vfprintf(g_logf, fmt, ap);
    fputc('\n', g_logf);
    fflush(g_logf);
    if (n > 0) g_bytes += n + 1;
}

void sel_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vline(stderr, "codeselect: ", fmt, ap);
    va_end(ap);
    va_start(ap, fmt);
    file_line(NULL, fmt, ap);
    va_end(ap);
}

void sel_say(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vline(stdout, "[select] ", fmt, ap);
    va_end(ap);
    va_start(ap, fmt);
    file_line("[select] ", fmt, ap);
    va_end(ap);
}
