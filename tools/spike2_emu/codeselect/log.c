/* log.c - see log.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include "log.h"

static FILE *g_logf;
static long g_t0 = -1;

long sel_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long)ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
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
    if (g_t0 < 0) g_t0 = sel_now_ms();
    if (!path || !*path) return 0;
    g_logf = fopen(path, "a");
    if (!g_logf) {
        fprintf(stderr, "codeselect: cannot open log %s: %s\n", path, strerror(errno));
        return -1;
    }
    setvbuf(g_logf, NULL, _IOLBF, 0);
    return 0;
}

void sel_log_close(void)
{
    if (g_logf) fclose(g_logf);
    g_logf = NULL;
}

static void stamp(char *buf, int n)
{
    long t;
    if (g_t0 < 0) g_t0 = sel_now_ms();
    t = sel_now_ms() - g_t0;
    snprintf(buf, n, "%5ld.%03ld", t / 1000, t % 1000);
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

void sel_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vline(stderr, "codeselect: ", fmt, ap);
    va_end(ap);
    if (g_logf) {
        va_start(ap, fmt);
        vline(g_logf, NULL, fmt, ap);
        va_end(ap);
    }
}

void sel_say(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vline(stdout, "[select] ", fmt, ap);
    va_end(ap);
    if (g_logf) {
        char ts[32];
        stamp(ts, sizeof ts);
        fprintf(g_logf, "%s [select] ", ts);
        va_start(ap, fmt);
        vfprintf(g_logf, fmt, ap);
        va_end(ap);
        fputc('\n', g_logf);
        fflush(g_logf);
    }
}
