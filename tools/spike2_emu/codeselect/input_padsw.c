/* input_padsw.c - the emulator's keyboard channel.
 *
 * padglhost writes key state into a 4096-byte file (struct padsw_shm in
 * tools/spike2_emu/padsw.h: magic 'PADS' 0x53444150 at 0, gen at 4, held[256]
 * at 8, scr_held[256] at 280 - the scripts' region), indexed by the title's
 * switch id. A switch is active when held[id] or scr_held[id]. The ids come
 * from the title's switch_list.txt ('# id num node bit name' rows), matched
 * by WIRE POSITION - the same resolution padglhost's own cab_wire table does,
 * and for the same reason: an id is a table index that drifts per generation,
 * and the names drift too. Without a table the platform ids padglhost
 * publishes before any table exists are used (36 start, 34 action, 25 select,
 * 26 plus, 27 minus, 28 back) and the flippers stay unknown.
 *
 * The Action button (node 1 bit 2, the one on the lockdown bar - Space in the
 * rig) also has a NAME fallback, used only when that wire is missing from the
 * list. Two spellings are in use across the 31 lists on this disk: 18 say
 * "LOCKDOWN BUTTON" (two of them with an "(OPTIONAL)" suffix), 11 say
 * "Action Button", and metallica_spike's list names nothing at all ('?').
 * The match is on the WHOLE name, case-insensitive: 'START BUTTON' as a
 * substring would also hit the 'TOURNAMENT START BUTTON' that 26 of those
 * lists carry, so nothing here matches loosely.
 *
 * The file is re-read every ~20 ms (a pread, so a re-created file is
 * harmless); it may not exist yet, so opening is retried every 500 ms.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include "input.h"
#include "log.h"

#define PADSW_MAGIC  0x53444150u
#define PADSW_BYTES  4096
#define OFF_GEN      4
#define OFF_HELD     8
#define OFF_SCR_HELD 280
#define POLL_MS      20
#define OPEN_MS      500
#define TABLE_MS     2000

struct ps {
    struct input base;
    char path[512], tables[512];
    int fd;
    long long next_open, next_poll, next_table;    /* sel_now_ms() deadlines: long long, see log.h */
    int id[KEY_COUNT];
    int have_table, open_logged, magic_logged;
    unsigned char buf[PADSW_BYTES];
};

/* the spellings the Action button's row carries, for the name fallback */
static const char *const action_names[] = { "ACTION BUTTON", "LOCKDOWN BUTTON", NULL };

static const struct {
    int node, bit;
    const char *name;                 /* the label in the log line */
    const char *const *alias;         /* names to accept when the wire is absent */
} wire[KEY_COUNT] = {
    { 8, 25, "left",   NULL }, { 8, 24, "right",  NULL },
    { 1, 11, "start",  NULL }, { 1,  2, "action", action_names },
    { 0,  8, "select", NULL }, { 0,  9, "plus",   NULL },
    { 0, 10, "minus",  NULL }, { 0, 11, "back",   NULL }
};

static void ids_platform(struct ps *p)
{
    int k;
    for (k = 0; k < KEY_COUNT; k++) p->id[k] = -1;
    p->id[KEY_OF(EV_START)] = 36;
    p->id[KEY_OF(EV_ACTION)] = 34;
    p->id[KEY_OF(EV_SELECT)] = 25;
    p->id[KEY_OF(EV_PLUS)] = 26;
    p->id[KEY_OF(EV_MINUS)] = 27;
    p->id[KEY_OF(EV_BACK)] = 28;
}

/* a switch name reduced to its comparable form: upper case, runs of blanks
 * collapsed to one, trimmed, and a trailing "(OPTIONAL)" dropped (two lists
 * spell the lockdown button that way) */
static void name_norm(char *out, int outlen, const char *s)
{
    int n = 0, sp = 0;
    for (; *s && n < outlen - 1; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') { sp = n > 0; continue; }
        if (sp) { out[n++] = ' '; sp = 0; if (n >= outlen - 1) break; }
        out[n++] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : (char)c;
    }
    out[n] = 0;
    if (n >= 11 && !strcmp(out + n - 11, " (OPTIONAL)")) out[n - 11] = 0;
}

static int name_is(const char *const *alias, const char *norm)
{
    int i;
    if (!alias || !*norm) return 0;
    for (i = 0; alias[i]; i++)
        if (!strcmp(alias[i], norm)) return 1;      /* whole name, never a substring */
    return 0;
}

static int table_load(struct ps *p)
{
    FILE *f = fopen(p->tables, "r");
    char line[512], norm[256], buf[300];
    int found = 0, named = 0, k, n = 0;
    int id[KEY_COUNT], byname[KEY_COUNT], from_name[KEY_COUNT];

    if (!f) return 0;
    for (k = 0; k < KEY_COUNT; k++) { id[k] = byname[k] = -1; from_name[k] = 0; }
    while (fgets(line, sizeof line, f)) {
        int sid, num, node, bit, pos = 0;
        char *s = line;
        while (*s == ' ' || *s == '\t') s++;
        if (*s == '#' || !*s) continue;
        if (sscanf(s, "%d %d %d %d%n", &sid, &num, &node, &bit, &pos) != 4) continue;
        if (sid < 0 || sid >= 256) continue;
        for (k = 0; k < KEY_COUNT; k++)
            if (wire[k].node == node && wire[k].bit == bit) {
                id[k] = sid;
                found++;
            }
        if (!pos) continue;
        name_norm(norm, sizeof norm, s + pos);
        for (k = 0; k < KEY_COUNT; k++)
            if (byname[k] < 0 && name_is(wire[k].alias, norm)) byname[k] = sid;
    }
    fclose(f);
    /* a key whose wire is not in this list, but whose name is */
    for (k = 0; k < KEY_COUNT; k++)
        if (id[k] < 0 && byname[k] >= 0) { id[k] = byname[k]; from_name[k] = 1; named++; }
    if (!found && !named) return 0;
    buf[0] = 0;
    for (k = 0; k < KEY_COUNT; k++) {
        int r;
        if (id[k] >= 0) p->id[k] = id[k];
        /* A key this list knows nothing about - neither its wire nor any of
         * its names - is NOT on this machine, so drop the platform id instead
         * of pointing it at whatever switch happens to hold that index. Only
         * the Action button carries names, and only it can be absent: the
         * beatles list has no lockdown row at all, and there id 34 is the
         * START button, which would have fired twice per press. */
        else if (wire[k].alias) p->id[k] = -1;
        r = snprintf(buf + n, sizeof buf - (size_t)n, " %s %d%s", wire[k].name, p->id[k],
                     from_name[k] ? " (by name)" : "");
        if (r < 0 || r >= (int)sizeof buf - n) break;      /* cannot happen; never overrun */
        n += r;
    }
    sel_log("padsw: ids from %s:%s", p->tables, buf);
    return found + named;
}

static void ps_poll(struct input *in, long long now)
{
    struct ps *p = (struct ps *)in;
    int k;

    if (!p->have_table && now >= p->next_table) {
        p->next_table = now + TABLE_MS;
        if (table_load(p)) p->have_table = 1;
    }
    if (p->fd < 0) {
        if (now < p->next_open) return;
        p->next_open = now + OPEN_MS;
        p->fd = open(p->path, O_RDONLY);
        if (p->fd < 0) {
            if (!p->open_logged) {
                sel_log("padsw: %s not there yet (%s), retrying every %d ms", p->path, strerror(errno), OPEN_MS);
                p->open_logged = 1;
            }
            return;
        }
        sel_log("padsw: %s open", p->path);
        p->open_logged = 0;
    }
    if (now < p->next_poll) return;
    p->next_poll = now + POLL_MS;
    {
        ssize_t n = pread(p->fd, p->buf, PADSW_BYTES, 0);
        unsigned magic;
        if (n < OFF_SCR_HELD + 256) {
            if (!p->magic_logged) {
                sel_log("padsw: short read (%ld bytes), reopening", (long)n);
                p->magic_logged = 1;
            }
            close(p->fd);
            p->fd = -1;
            p->next_open = now + OPEN_MS;
            return;
        }
        memcpy(&magic, p->buf, 4);
        if (magic != PADSW_MAGIC) {
            if (!p->magic_logged) {
                sel_log("padsw: bad magic 0x%08x, waiting for padglhost", magic);
                p->magic_logged = 1;
            }
            return;
        }
        p->magic_logged = 0;
    }
    for (k = 0; k < KEY_COUNT; k++) {
        int id = p->id[k];
        if (id < 0) continue;
        input_sample(in, k, p->buf[OFF_HELD + id] || p->buf[OFF_SCR_HELD + id]);
    }
}

static void ps_close(struct input *in)
{
    struct ps *p = (struct ps *)in;
    if (p->fd >= 0) close(p->fd);
    free(p);
}

static const struct input_ops ps_ops = { ps_poll, ps_close };

struct input *input_padsw_open(const struct input_cfg *cfg)
{
    struct ps *p = calloc(1, sizeof *p);
    if (!p) return NULL;
    input_base_init(&p->base, &ps_ops);
    p->fd = -1;
    snprintf(p->path, sizeof p->path, "%s", cfg->padsw ? cfg->padsw : "/dump/padsw");
    snprintf(p->tables, sizeof p->tables, "%s", cfg->tables ? cfg->tables : "");
    ids_platform(p);
    if (*p->tables && table_load(p)) p->have_table = 1;
    else sel_log("padsw: no switch table at '%s' yet: platform ids only (start 36, action 34, service 25-28)", p->tables);
    sel_log("padsw: reading %s every %d ms", p->path, POLL_MS);
    return &p->base;
}
