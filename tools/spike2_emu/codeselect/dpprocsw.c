/* dpprocsw.c - the cabinet buttons of a Dutch Pinball machine (The Big
 * Lebowski), read off its P3-ROC through THE GAME'S OWN libpinproc, for the
 * boot menu (PAD-853, tools/dp_emu/MULTIBOOT.md).
 *
 *     dpprocsw [--machine pdb|<n>] [--period MS] NAME=SWITCH ...
 *
 * NAME is what to print (L, R, S ...); SWITCH is the switch as the game's
 * config/machine.yaml writes it ("SD67" or "67"), read the way the game's
 * own dp/pdb.py PDBSwitch reads it: "SD<n>" is dedicated switch n and its
 * P-ROC number is n.  (libpinproc's PRDecode is NOT the game's rule: on a
 * PDB machine it reads "SD67" as 0.)  A matrix address ("c/r") is refused;
 * no cabinet button of The Big Lebowski is one.  Printed on stdout, one
 * line each:
 *
 *     ready            the board answered; the levels below are from now on
 *     sw NAME 1|0      NAME is closed (pressed) / open; every NAME once after
 *                      ready, then on every change
 *     wait <why>       no board yet (retried every second, said once)
 *
 * The menu (dpselect --input pipe:0) reads these; it exits when the menu
 * closes the pipe (a write fails).
 *
 * WHY A PROGRAM OF ITS OWN.  dpselect is one STATIC program (the machine's
 * Arch root is whatever its last system image carried), and a static program
 * cannot load a library.  The P3-ROC is reached through libpinproc ->
 * libftdi1 -> libusb, which every version folder of the game carries beside
 * its program; this program links libpinproc.so.2.0 by name, and the
 * launcher runs it with LD_LIBRARY_PATH at a version folder, so it opens the
 * board exactly the way the game does.
 *
 * THE GLIBC IT NEEDS IS 2.2.5.  It is built on a newer host, where crt1.o
 * calls __libc_start_main@GLIBC_2.34 and the machine's loader would refuse
 * it.  So it is linked -nostartfiles with its own _start (below): the loader
 * still runs libc's initialisers before jumping here, and every libc
 * function used is one that has had its version since 2.2.5.
 * test/check_elf_dp.sh proves the ceiling.
 *
 * WHAT IS WRITTEN TO THE BOARD is PRCreate's: the library resets the board
 * the way the game does at its own start (every driver off).  Nothing is
 * configured and no driver is ever enabled, so no coil can fire.
 *
 * PRESSED = CLOSED.  PRSwitchGetStates reports each switch's debounced level;
 * the flippers and START are normally-open buttons, so closed is pressed.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* ---- libpinproc's C interface (pinproc.h), what is used of it ---------- */
typedef void *PRHandle;
typedef int PRResult;                      /* kPRSuccess = 1 */
typedef int PRMachineType;                 /* kPRMachinePDB = 7 */
typedef int PREventType;                   /* 1/3 closed, 2/4 open */
PRHandle PRCreate(PRMachineType machineType);
void PRDelete(PRHandle handle);
PRResult PRSwitchGetStates(PRHandle handle, PREventType *states, uint16_t n);
const char *PRGetLastErrorText(void);

#define MACHINE_PDB 7
#define NSW 256                            /* P-ROC switch numbers 0..255 */
#define MAXB 8

#ifndef DPPROCSW_NO_START
/* the loader has run libc's initialisers; set up main's arguments and leave
 * through exit() so stdio is flushed */
int dpprocsw_main(int argc, char **argv);
__asm__(".text\n"
        ".global _start\n"
        "_start:\n"
        "  xor %ebp, %ebp\n"
        "  mov (%rsp), %rdi\n"
        "  lea 8(%rsp), %rsi\n"
        "  and $-16, %rsp\n"
        "  call dpprocsw_main\n"
        "  mov %eax, %edi\n"
        "  call exit\n"
        "  hlt\n");
#define main dpprocsw_main
#endif

static int out(const char *s)
{
    size_t n = strlen(s);
    return fwrite(s, 1, n, stdout) == n && fflush(stdout) == 0;
}

/* "SD67" / "sd67" / "67" -> 67, as dp/pdb.py PDBSwitch; -1 for anything else */
static int switch_number(const char *s)
{
    int n = 0, any = 0;
    if ((s[0] == 'S' || s[0] == 's') && (s[1] == 'D' || s[1] == 'd'))
        s += 2;
    for (; *s >= '0' && *s <= '9'; s++, any = 1)
        n = n * 10 + (*s - '0');
    return any && !*s && n < 2048 ? n : -1;
}

static int closed_of(PREventType t)
{
    return t == 1 || t == 3;
}

int main(int argc, char **argv)
{
    const char *name[MAXB];
    int sw[MAXB], last[MAXB];
    int nb = 0, period = 20, machine = MACHINE_PDB, said = 0, i;
    char line[96];

    for (i = 1; i < argc; i++) {
        char *eq;
        if (!strcmp(argv[i], "--machine") && i + 1 < argc) {
            i++;
            machine = !strcmp(argv[i], "pdb") ? MACHINE_PDB : atoi(argv[i]);
        } else if (!strcmp(argv[i], "--period") && i + 1 < argc) {
            period = atoi(argv[++i]);
            if (period < 5)
                period = 5;
        } else if ((eq = strchr(argv[i], '=')) && eq > argv[i] && eq[1] && nb < MAXB) {
            *eq = 0;
            name[nb] = argv[i];
            sw[nb] = switch_number(eq + 1);
            if (sw[nb] < 0 || sw[nb] >= NSW) {
                fprintf(stderr, "dpprocsw: %s=%s is not a dedicated switch 0-%d\n",
                        argv[i], eq + 1, NSW - 1);
                return 2;
            }
            fprintf(stderr, "dpprocsw: %s = %s = switch %d\n", argv[i], eq + 1, sw[nb]);
            last[nb] = -1;
            nb++;
        } else {
            fprintf(stderr, "usage: dpprocsw [--machine pdb|N] [--period MS] NAME=SWITCH ...\n");
            return 2;
        }
    }
    if (!nb) {
        fprintf(stderr, "dpprocsw: no switches named\n");
        return 2;
    }

    for (;;) {
        PREventType st[NSW];
        PRHandle h = PRCreate(machine);
        if (!h) {
            if (!said) {
                const char *e = PRGetLastErrorText();
                int n;
                snprintf(line, sizeof line, "wait %.80s", e && *e ? e : "no board");
                for (n = 5; line[n]; n++)
                    if ((unsigned char)line[n] < ' ')
                        line[n] = ' ';
                line[n] = '\n';
                line[n + 1] = 0;
                if (!out(line))
                    return 0;
                said = 1;
            }
            usleep(1000 * 1000);
            continue;
        }
        if (!out("ready\n")) {
            PRDelete(h);
            return 0;
        }
        for (;;) {
            if (PRSwitchGetStates(h, st, NSW) != 1) {
                fprintf(stderr, "dpprocsw: reading the switches failed: %s\n", PRGetLastErrorText());
                break;
            }
            for (i = 0; i < nb; i++) {
                int c = closed_of(st[sw[i]]);
                if (c != last[i]) {
                    last[i] = c;
                    snprintf(line, sizeof line, "sw %s %d\n", name[i], c);
                    if (!out(line)) {
                        PRDelete(h);
                        return 0;
                    }
                }
            }
            usleep((useconds_t)period * 1000);
        }
        PRDelete(h);
        for (i = 0; i < nb; i++)
            last[i] = -1;
        said = 0;
        usleep(1000 * 1000);
    }
}
