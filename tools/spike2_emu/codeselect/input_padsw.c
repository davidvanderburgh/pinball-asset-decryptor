/* input_padsw.c - the emulator's keyboard channel.
 *
 * padglhost writes key state into a 4096-byte file (struct padsw_shm in
 * tools/spike2_emu/padsw.h: magic 'PADS' 0x53444150 at 0, gen at 4, held[256]
 * at 8, scr_held[256] at 280 - the scripts' region), indexed by the title's
 * switch id. A switch is active when held[id] or scr_held[id]. The ids come
 * from the title's switch_list.txt ('# id num node bit name' rows), matched
 * by wire position; without a table the platform ids padglhost publishes
 * before any table exists are used (36 start, 25 select, 26 plus, 27 minus,
 * 28 back) and the flippers stay unknown.
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
    long next_open, next_poll, next_table;
    int id[KEY_COUNT];
    int have_table, open_logged, magic_logged;
    unsigned char buf[PADSW_BYTES];
};

static const struct { int node, bit; const char *name; } wire[KEY_COUNT] = {
    { 8, 25, "LEFT" }, { 8, 24, "RIGHT" }, { 1, 11, "START" },
    { 0, 8, "SELECT" }, { 0, 9, "PLUS" }, { 0, 10, "MINUS" }, { 0, 11, "BACK" }
};

static void ids_platform(struct ps *p)
{
    int k;
    for (k = 0; k < KEY_COUNT; k++) p->id[k] = -1;
    p->id[KEY_OF(EV_START)] = 36;
    p->id[KEY_OF(EV_SELECT)] = 25;
    p->id[KEY_OF(EV_PLUS)] = 26;
    p->id[KEY_OF(EV_MINUS)] = 27;
    p->id[KEY_OF(EV_BACK)] = 28;
}

static int table_load(struct ps *p)
{
    FILE *f = fopen(p->tables, "r");
    char line[512];
    int found = 0, k;
    int id[KEY_COUNT];

    if (!f) return 0;
    for (k = 0; k < KEY_COUNT; k++) id[k] = -1;
    while (fgets(line, sizeof line, f)) {
        int sid, num, node, bit;
        char *s = line;
        while (*s == ' ' || *s == '\t') s++;
        if (*s == '#' || !*s) continue;
        if (sscanf(s, "%d %d %d %d", &sid, &num, &node, &bit) != 4) continue;
        for (k = 0; k < KEY_COUNT; k++)
            if (wire[k].node == node && wire[k].bit == bit && sid >= 0 && sid < 256) {
                id[k] = sid;
                found++;
            }
    }
    fclose(f);
    if (!found) return 0;
    for (k = 0; k < KEY_COUNT; k++)
        if (id[k] >= 0) p->id[k] = id[k];
    sel_log("padsw: ids from %s: left %d right %d start %d select %d plus %d minus %d back %d",
            p->tables, p->id[0], p->id[1], p->id[2], p->id[3], p->id[4], p->id[5], p->id[6]);
    return found;
}

static void ps_poll(struct input *in, long now)
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
    else sel_log("padsw: no switch table at '%s' yet: platform ids only (start 36, service 25-28)", p->tables);
    sel_log("padsw: reading %s every %d ms", p->path, POLL_MS);
    return &p->base;
}
