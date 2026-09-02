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
 * publishes before any table exists are used (36 start, 25 select, 26 plus,
 * 27 minus, 28 back) and the flippers - and the Action button - stay unknown.
 *
 * The Action button (node 1 bit 2, the one on the lockdown bar - Space in the
 * rig) also has a NAME fallback, used only when that wire is missing from the
 * list. Two spellings are in use across the 31 title lists on this disk: 17
 * say "LOCKDOWN BUTTON" (two of those with an "(OPTIONAL)" suffix), 12 say
 * "Action Button", and metallica_spike's list names nothing at all ('?').
 * The match is on the WHOLE name, case-insensitive: 'START BUTTON' as a
 * substring would also hit the 'TOURNAMENT START BUTTON' that 26 of those
 * lists carry, so nothing here matches loosely.
 *
 * The file is re-read every ~20 ms (a pread, so a re-created file is
 * harmless); it may not exist yet, so opening is retried every 500 ms. The
 * switch list is re-read whenever its mtime moves, for the reason padglhost
 * re-resolves its own binds - see table_load().
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "input.h"
#include "log.h"

#define PADSW_MAGIC  0x53444150u
#define PADSW_BYTES  4096
#define OFF_GEN      4
#define OFF_HELD     8
#define OFF_SCR_HELD 280
#define POLL_MS      20
#define OPEN_MS      500
#define TABLE_MS     2000        /* re-stat an already-parsed list this often */
#define TABLE_WAIT_MS 250        /* ...but hunt for a missing one four times a second */

struct ps {
    struct input base;
    char path[512], tables[512];
    int fd;
    long long next_open, next_poll, next_table;    /* sel_now_ms() deadlines: long long, see log.h */
    int id[KEY_COUNT];
    int have_table, open_logged, magic_logged;
    struct timespec mtim;             /* mtime of the list p->id came from */
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

/* what the menu may promise and what it may read: a key with no switch id can
 * never fire, and draw_menu()'s footer names only the buttons that can */
static void ids_publish(struct ps *p)
{
    int k;
    for (k = 0; k < KEY_COUNT; k++) p->base.present[k] = p->id[k] >= 0;
}

/* ★ THE ACTION BUTTON GETS NO PRE-TABLE ID, AND THAT IS THE WHOLE POINT.
 *
 * These are the ids padglhost publishes before a switch list resolves. They
 * are a guess about a table index, and the guess is wrong on a third of the
 * lists on this disk - which for most keys costs a dead or shifted button, but
 * for the Action button cost the menu its consent.
 *
 * Swept over the 31 cached switch_list.txt files: platform id 34 is the
 * lockdown-bar button on 20 of them, but on SEVEN it is COIN DOOR INTERLOCK
 * (node 0 bit 23) - aerosmith_le, avengers_infinity_le, foo_fighters_le,
 * guardians_le, iron_maiden_le, mando_le, rush_le. That switch is not a
 * button: a shut coin door holds it MADE, which is the normal state of a
 * machine (padglhost latches it at window open, padglhost.c:1814, "otherwise
 * the game draws * 48V DISABLED *"), and on real hardware nobody opens the
 * door to boot. So on those seven titles a menu that read id 34 read a
 * permanently-made switch as an ACTION press and confirmed the highlighted
 * image instantly, untouched. Id 34 is also VOLUME ENCODER 1 on batman and
 * the START button on beatles.
 *
 * There is no id here that is right often enough to be worth that, so ACTION
 * waits for the table (or for its name); until then EV_ACTION cannot fire at
 * all, and input_has() tells the footer to say so. It loses least by waiting:
 * it is the only key with a NAME fallback, so a list that has the button at
 * all resolves it either way.
 *
 * The same sweep on the other keys. 25-28 slide onto DIP 8 / SERVICE SELECT /
 * SERVICE PLUS / SERVICE MINUS on the eight older lists, so the service
 * cluster is off by one until the table lands; none of those is ever held
 * made, so the worst they do is move the highlight. 36 is TICKET NOTCH on
 * eight lists and Left Coin on beatles - dead keys, not dangerous ones.
 *
 * ONE residual collision is knowingly left standing: on BATMAN id 36 is that
 * same COIN DOOR INTERLOCK, so pre-table START carries the hazard ACTION just
 * lost. It is not dropped because 36 is right on 20 lists and START would
 * otherwise be the only confirm key a table-less menu has - dropping it makes
 * 30 titles unbootable-by-hand to disarm one. What actually fires it is not
 * the door's LEVEL (a switch already made when the first sample lands sets the
 * debouncer's first settled level and raises no edge - input.c) but a RISING
 * edge, i.e. padglhost re-resolving id 36 from 33 to the door while this menu
 * is still on platform ids. So the window is closed from the other end: with
 * no table the list is re-checked every TABLE_WAIT_MS, not TABLE_MS, and a
 * list that exists is picked up within a quarter second of appearing.
 */
static void ids_platform(struct ps *p)
{
    int k;
    for (k = 0; k < KEY_COUNT; k++) p->id[k] = -1;
    p->id[KEY_OF(EV_START)] = 36;
    p->id[KEY_OF(EV_SELECT)] = 25;
    p->id[KEY_OF(EV_PLUS)] = 26;
    p->id[KEY_OF(EV_MINUS)] = 27;
    p->id[KEY_OF(EV_BACK)] = 28;
    ids_publish(p);
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

/* Parse a switch list into id[] (-1 = this list does not carry the key) and
 * from_name[] (1 = matched by name, not by wire). Returns how many keys it
 * resolved: 0 for a file that cannot be read or holds no row this menu wants.
 * Pure - it touches no state, so --snapshot can call it too. */
static int table_scan(const char *path, int id[KEY_COUNT], int from_name[KEY_COUNT])
{
    FILE *f = fopen(path, "r");
    char line[512], norm[256];
    int found = 0, named = 0, k;
    int byname[KEY_COUNT];

    for (k = 0; k < KEY_COUNT; k++) { id[k] = byname[k] = -1; from_name[k] = 0; }
    if (!f) return 0;
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
    return found + named;
}

/* ★ RESOLVED IS NOT FOREVER. This used to latch on the first successful parse
 * and never look again, which loses a race padglhost already learned to lose
 * gracefully (padglhost.c:2008-2030): mktables REPAIRS a partly-derived list
 * about a second into a run - a cached all-'?' table gets its names filled
 * from the device table - and a menu that read the file in that first second
 * kept the poorer answer for its whole life. For this menu the poorer answer
 * is specifically the Action button, whose name fallback is the only thing an
 * all-'?' list cannot give it. So the list is re-read whenever its mtime
 * moves; a rewrite that parses to nothing leaves the standing ids (and the
 * recorded mtime) alone, so a later good write still re-resolves. */
static int table_load(struct ps *p)
{
    char buf[300];
    struct stat st;
    int k, n = 0, got;
    int id[KEY_COUNT], from_name[KEY_COUNT];

    got = table_scan(p->tables, id, from_name);
    if (!got) return 0;
    if (stat(p->tables, &st) == 0) p->mtim = st.st_mtim;
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
    ids_publish(p);
    sel_log("padsw: ids from %s:%s", p->tables, buf);
    return got;
}

/* the list changed on disk since the ids in p->id were read off it */
static int table_moved(struct ps *p)
{
    struct stat st;
    if (!*p->tables || stat(p->tables, &st) != 0) return 0;
    return st.st_mtim.tv_sec != p->mtim.tv_sec || st.st_mtim.tv_nsec != p->mtim.tv_nsec;
}

static void ps_poll(struct input *in, long long now)
{
    struct ps *p = (struct ps *)in;
    int k;

    if (now >= p->next_table) {
        p->next_table = now + (p->have_table ? TABLE_MS : TABLE_WAIT_MS);
        if (!p->have_table) {
            if (table_load(p)) p->have_table = 1;
        } else if (table_moved(p) && table_load(p)) {
            sel_log("padsw: %s changed on disk; ids re-resolved", p->tables);
        }
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
    else sel_log("padsw: no switch table at '%s' yet: platform ids only "
                 "(start 36, service 25-28); the ACTION button stays unresolved "
                 "and cannot fire", p->tables);
    sel_log("padsw: reading %s every %d ms", p->path, POLL_MS);
    return &p->base;
}

int input_padsw_has_action(const char *tables)
{
    int id[KEY_COUNT], from_name[KEY_COUNT];
    if (!tables || !*tables) return 0;
    return table_scan(tables, id, from_name) > 0 && id[KEY_OF(EV_ACTION)] >= 0;
}
