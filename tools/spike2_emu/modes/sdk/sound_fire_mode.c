/* sound_fire_mode.c - play, poll and stop sound requests by hand, from a trigger file (item 150).
 *
 * Not a game mode: a rig instrument built with the SDK, next to mode_file.c when a run needs
 * both (the census, sound_census.c, cannot share a game with mode.so: both hook the tick).
 *   build_mode.sh -o mode.so mode_file.c sound_fire_mode.c
 * Twice a second it looks for, in /dump:
 *   sound.fire    "<request>"   pm_sound(request)
 *   sound.active  "<request>"   logs pm_sound_active(request)
 *   sound.stop    "<request>"   pm_sound_stop(request)
 *   sound.prio    "<request> <priority> <flags>"   pm_sound_priority (-1 leaves one as it is)
 *   sound.dump    "<ms>"        every <ms> (0 = off), the channels playing, logged when they change
 *   sound.sid     "<request> <sid>"  pm_sound_sid (sid 0 puts the request's own list back)
 *   sound.fade    "<request> <ms>"   pm_sound_fade, then its voices' volume steps logged twice
 *                               a second until it is over (item 150 follow-up)
 *   callout.one   "<request>"        pm_callout (the port's callout site: a mode's end call)
 *   callout.nth   "<request> <n>"    pm_callout_nth (a mode's countdown plays n = seconds - 1)
 *                               (item 163, modes/voicecheck.sh)
 *   key.play      "<request> <stock key> <our key> <priority> <ms>"  (keys: 16 hex digits)
 *                               pm_sound_swap then pm_sound: the carrier plays the record `our key`
 *                               names (item 163); the bus of the channel that plays it is logged
 *                               once (pm_sound_playing), and the runtime puts the key back itself
 * and logs each as "[soundfire] ..." in /dump/mode.log. Works in attract too: nothing here
 * waits for a game.
 *
 * A channel dump line: "ch <n>:<request> p<priority> f<flags> b<bus bits> s<serial>" for each
 * channel with a voice playing (the worker's channel struct: +180 serial, +184 request,
 * +186 priority, +187 flags, +188 voices, +189 bus bits). The table's address is the port's
 * `data sound_channels`, read from /dump/game.port.
 */
#include "pad_mode.h"

static unsigned number(const char *s)
{
    unsigned v = 0;
    while (*s == ' ') s++;
    while (*s >= '0' && *s <= '9') v = v * 10 + (unsigned)(*s++ - '0');
    return v;
}

static const char *signed_number(const char *s, int *out)
{
    int neg = 0, v = 0;
    while (*s == ' ') s++;
    if (*s == '-') { neg = 1; s++; }
    while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0');
    *out = neg ? -v : v;
    return s;
}

static unsigned hexnum(const char *s)
{
    unsigned v = 0;
    while (*s == ' ') s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    for (;; s++) {
        if (*s >= '0' && *s <= '9') v = v * 16 + (unsigned)(*s - '0');
        else if (*s >= 'a' && *s <= 'f') v = v * 16 + (unsigned)(*s - 'a' + 10);
        else if (*s >= 'A' && *s <= 'F') v = v * 16 + (unsigned)(*s - 'A' + 10);
        else break;
    }
    return v;
}

/* the port's `data sound_channels` address, or 0 */
static unsigned channels_address(void)
{
    static char port[32768];
    static const char key[] = "data sound_channels";
    long n = pm_read_file("/dump/game.port", port, sizeof port - 1);
    long i;
    unsigned k;
    if (n <= 0) return 0;
    port[n] = 0;
    for (i = 0; i < n; i++) {
        if (i && port[i - 1] != '\n') continue;
        for (k = 0; key[k] && port[i + k] == key[k]; k++) ;
        if (!key[k]) return hexnum(port + i + k);
    }
    return 0;
}

static unsigned dump_ms, dump_last_ms, chan_table, vol_watch;
static unsigned long vol_until;
static unsigned key_watch;             /* item 163: key.play's request, until its bus is logged */
static unsigned long key_until;
static char dump_last[512];

static void dump_channels(void)
{
    char line[512];
    unsigned c, o = 0;
    const unsigned char *ch;
    line[0] = 0;
    for (c = 0; c < 8; c++) {
        ch = (const unsigned char *)(unsigned long)(chan_table + c * 196);
        if (!ch[188]) continue;
        o += (unsigned)pm_snprintf(line + o, sizeof line - o, " %u:%u p%u f%u b%02x s%u", c,
                                   (unsigned)(ch[184] | ch[185] << 8), ch[186], ch[187], ch[189],
                                   (unsigned)(ch[180] | ch[181] << 8 | ch[182] << 16 | (unsigned)ch[183] << 24));
        if (o >= sizeof line - 48) break;
    }
    for (c = 0; line[c] == dump_last[c] && line[c]; c++) ;
    if (line[c] == dump_last[c]) return;
    for (c = 0; (dump_last[c] = line[c]) != 0; c++) ;
    pm_log("ch%s", line[0] ? line : " (none playing)");
}

/* 16 hex digits -> 8 bytes; the text after them, or 0 */
static const char *hex_key(const char *s, unsigned char out[8])
{
    int i;
    while (*s == ' ') s++;
    for (i = 0; i < 16; i++) {
        int c = s[i], v = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10
                        : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (v < 0) return 0;
        if (i & 1) out[i / 2] = (unsigned char)(out[i / 2] | v); else out[i / 2] = (unsigned char)(v << 4);
    }
    return s + 16;
}

static void on_init(void)
{
    pm_log("ready on %s %s: sound.fire / sound.active / sound.stop / sound.prio / sound.dump", pm_game(), pm_version());
}

static void on_tick(void)
{
    static unsigned ticks;
    char text[96];
    unsigned req;
    ticks++;
    if (dump_ms && chan_table && pm_ms() - dump_last_ms >= dump_ms) {
        dump_last_ms = (unsigned)pm_ms();
        dump_channels();
    }
    if (ticks % 30) return;
    if (pm_trigger_text("sound.fire", text, sizeof text)) {
        req = number(text);
        pm_log("fire %u: %s", req, pm_sound(req) ? "called" : "NOT called (no sound_play in the port)");
    }
    if (pm_trigger_text("sound.active", text, sizeof text)) {
        req = number(text);
        pm_log("active %u: %d", req, pm_sound_active(req));
    }
    if (pm_trigger_text("sound.stop", text, sizeof text)) {
        req = number(text);
        pm_log("stop %u: %d", req, pm_sound_stop(req));
    }
    if (pm_trigger_text("sound.prio", text, sizeof text)) {
        int r, prio, flags, old;
        const char *s = signed_number(text, &r);
        s = signed_number(s, &prio);
        signed_number(s, &flags);
        old = pm_sound_priority((unsigned)r, prio, flags);
        pm_log("prio %d -> %d %d: was %d %d", r, prio, flags, old < 0 ? -1 : old >> 8, old < 0 ? -1 : old & 0xff);
    }
    if (pm_trigger_text("sound.dump", text, sizeof text)) {
        dump_ms = number(text);
        if (!chan_table) chan_table = channels_address();
        dump_last[0] = 1; dump_last[1] = 0;   /* log the first dump whatever it holds */
        pm_log("dump every %u ms (channels at 0x%08x)", dump_ms, chan_table);
    }
    /* item 150 follow-up: a request pointed at one sid, a fade, and the voices' volume steps */
    if (pm_trigger_text("sound.sid", text, sizeof text)) {
        int r, sid;
        const char *s = signed_number(text, &r);
        signed_number(s, &sid);
        pm_log("sid %d -> %d: %d", r, sid, pm_sound_sid((unsigned)r, (unsigned)sid));
    }
    if (pm_trigger_text("sound.fade", text, sizeof text)) {
        int r, ms;
        const char *s = signed_number(text, &r);
        signed_number(s, &ms);
        pm_log("fade %d over %d ms: %d", r, ms, pm_sound_fade((unsigned)r, (unsigned)ms));
        vol_watch = (unsigned)r;
        vol_until = pm_ms() + (unsigned)ms + 300;
    }
    /* item 163: the port's callout sites, exactly as a mode's countdown and end call use them */
    if (pm_trigger_text("callout.one", text, sizeof text)) {
        req = number(text);
        pm_callout(req);
        pm_log("callout %u", req);
    }
    if (pm_trigger_text("callout.nth", text, sizeof text)) {
        int r, n;
        const char *s = signed_number(text, &r);
        signed_number(s, &n);
        pm_callout_nth((unsigned)r, (unsigned)n);
        pm_log("callout_nth %d %d", r, n);
    }
    /* item 163: a carrier's own record key swapped for another's, for one play */
    if (pm_trigger_text("key.play", text, sizeof text)) {
        unsigned char stock[8], ours[8];
        int r, prio, ms, ok;
        const char *s = signed_number(text, &r);
        s = hex_key(s, stock);
        s = s ? hex_key(s, ours) : 0;
        if (!s) {
            pm_log("key.play: needs <request> <stock key> <our key> <priority> <ms>, keys 16 hex digits");
        } else {
            s = signed_number(s, &prio);
            signed_number(s, &ms);
            ok = pm_sound_swap((unsigned)r, stock, ours, prio, (unsigned)ms);
            pm_log("key %d -> %02x%02x%02x%02x%02x%02x%02x%02x at priority %d for %d ms: %s", r, ours[0], ours[1], ours[2],
                   ours[3], ours[4], ours[5], ours[6], ours[7], prio, ms,
                   !ok ? "NOT armed" : pm_sound((unsigned)r) ? "played" : "armed, NOT played (no sound_play)");
            key_watch = ok ? (unsigned)r : 0;
            key_until = pm_ms() + 2000;
        }
    }
    if (key_watch) {
        unsigned reqs[8], buses[8];
        int n = pm_sound_playing(reqs, buses, 8), i;
        for (i = 0; i < n && i < 8; i++)
            if (reqs[i] == key_watch) {
                pm_log("key %u plays on bus 0x%02x", key_watch, buses[i]);
                key_watch = 0;
                break;
            }
        if (key_watch && (n < 0 || pm_ms() > key_until)) {
            pm_log("key %u: %s", key_watch, n < 0 ? "no channel table in the port (bus not read)" : "no channel played it");
            key_watch = 0;
        }
    }
    if (vol_watch && chan_table) {
        char line[160];
        unsigned c, b, o = 0;
        for (c = 0; c < 8; c++) {
            const unsigned char *ch = (const unsigned char *)(unsigned long)(chan_table + c * 196);
            if (!ch[188] || (unsigned)(ch[184] | ch[185] << 8) != vol_watch) continue;
            for (b = 0; b < 8; b++)
                if (ch[188] >> b & 1u) {
                    const unsigned char *v = (const unsigned char *)(unsigned long)*(const unsigned *)(ch + 92 + 4 * b);
                    if (v) o += (unsigned)pm_snprintf(line + o, sizeof line - o, " %u.%u:%u", c, b,
                                                      (unsigned)(v[48] | v[49] << 8));
                    if (o >= sizeof line - 16) break;
                }
        }
        line[o] = 0;
        pm_log("vol %u:%s", vol_watch, o ? line : " (not playing)");
        if (pm_ms() > vol_until) vol_watch = 0;
    }
}

static const struct pm_mode sound_fire = {
    .name = "soundfire",
    .init = on_init,
    .tick = on_tick,
};
PM_REGISTER(sound_fire);
