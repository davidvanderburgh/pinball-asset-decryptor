/* PAD-1448 prototype: give Stranger Things LE 1.13 23 RGB speaker lights on node 2 (device group 1),
 * before the game's own static initialisers read its light and device tables.
 * Preloaded through PAD_TRACE_SO. Refuses unless both count constants read what the file holds. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/mman.h>

#define LIGHT_CONST   0x5dc620u   /* 340: copied into the light count at start-up */
#define DEV_CONST     0x5dc75cu   /* 459: copied into the device count */
#define LIGHT_PTR     0x7c7994u   /* -> light table, 24-byte records */
#define DEV_PTR       0x7c74dcu   /* -> device table, 48-byte records */
#define CLONE_LIGHT   122         /* TOPPER 1-R */
#define CLONE_DEV     244
#define NLED          23
#define NEW           (NLED * 3)

static char names[NEW][24];

__attribute__((constructor)) static void spk_init(void)
{
    volatile uint32_t *lc = (uint32_t *)LIGHT_CONST, *dc = (uint32_t *)DEV_CONST;
    uint32_t nl = *lc, nd = *dc;
    FILE *log = fopen("/dump/spkprobe.log", "w");
    if (nl != 340 || nd != 459) {
        if (log) { fprintf(log, "not ST LE 1.13 (lights %u devices %u): nothing done\n", nl, nd); fclose(log); }
        return;
    }
    uint8_t *ol = *(uint8_t **)LIGHT_PTR, *od = *(uint8_t **)DEV_PTR;
    /* lights 0..339, then the trailer record 340 and a zero record: keep both after ours */
    uint8_t *L = calloc(nl + NEW + 4, 24), *D = calloc(nd + NEW + 4, 48);
    memcpy(L, ol, 24 * nl);
    memcpy(L + 24 * (nl + NEW), ol + 24 * nl, 48);
    memcpy(D, od, 48 * nd);
    memcpy(D + 48 * (nd + NEW), od + 48 * nd, 48);
    static const char col[3] = {'G', 'R', 'B'};          /* the boards' channel order, as Godzilla's */
    for (int k = 0; k < NEW; k++) {
        int led = k / 3, c = k % 3;
        snprintf(names[k], sizeof names[k], "SPEAKER %d-%c", led + 1, col[c]);
        uint8_t *d = D + 48 * (nd + k), *l = L + 24 * (nl + k);
        memcpy(d, od + 48 * CLONE_DEV, 48);
        *(uint32_t *)(d + 0x0C) = (uint32_t)(uintptr_t)names[k];
        *(int16_t *)(d + 0x1C) = 1;                       /* group 1 = node 2, Cabinet Lights */
        *(int16_t *)(d + 0x1E) = (int16_t)k;              /* channel on the board */
        memcpy(l, ol + 24 * CLONE_LIGHT, 24);
        *(uint32_t *)(l + 0x00) = (uint32_t)(uintptr_t)names[k];
        *(uint16_t *)(l + 0x0C) = (uint16_t)(396 + k);    /* a slot past the game's own 0..395 */
        *(uint16_t *)(l + 0x0E) = (uint16_t)(nd + k);
    }
    uintptr_t pg = LIGHT_CONST & ~0xfffu;
    if (mprotect((void *)pg, 0x2000, PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
        if (log) { fprintf(log, "mprotect failed\n"); fclose(log); }
        return;
    }
    *lc = nl + NEW;
    *dc = nd + NEW;
    mprotect((void *)pg, 0x2000, PROT_READ | PROT_EXEC);
    *(uint8_t **)LIGHT_PTR = L;
    *(uint8_t **)DEV_PTR = D;
    if (log) {
        fprintf(log, "added %d speaker lights: lights %u -> %u (ids %u..%u), devices %u -> %u, group 1 channels 0..%d\n",
                NEW, nl, nl + NEW, nl, nl + NEW - 1, nd, nd + NEW, NEW - 1);
        fclose(log);
    }
}
