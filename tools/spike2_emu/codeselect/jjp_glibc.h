/* jjp_glibc.h - force-included (-include) into every JJP-build translation
 * unit, BEFORE any other header.
 *
 * THE TRAP.  The WSL host that builds jjpselect runs glibc 2.39; the JJP
 * card runs 2.34.  From 2.38 on, glibc's headers redirect strtol, strtoul,
 * sscanf and their relatives to __isoc23_* symbols whenever
 * _ISOC2X_SOURCE is set - and _GNU_SOURCE (which every file here defines)
 * sets it.  A binary built that way loads on the host and dies on the card
 * before main():
 *
 *     symbol lookup error: undefined symbol: __isoc23_strtol
 *
 * tools/jjp_emu/build.sh met exactly this with the hardware shim.  The
 * redirect is gated on one macro that features.h computes and nothing
 * else re-computes, so it is switched off here, once, after features.h has
 * had its say.  test/check_elf_jjp.sh then proves it: no GLIBC_2.35+
 * version node, and (with a card image mounted) every undefined symbol
 * resolving against the card's own libraries.
 *
 * _GNU_SOURCE IS DEFINED HERE, before features.h (PAD-449).  Being first,
 * this header is where features.h runs, and it runs once: a file's own
 * `#define _GNU_SOURCE` after it changes nothing.  Without the line below the
 * whole JJP build compiled with no __USE_GNU at all.  2.39 happens to declare
 * memmem under __USE_MISC; a Mac's toolbox container (Debian 12, glibc 2.36)
 * declares it under __USE_GNU only, so colour.c's memmem was an implicit
 * declaration there and the menu program never built.
 */
#ifndef CODESELECT_JJP_GLIBC_H
#define CODESELECT_JJP_GLIBC_H
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <features.h>
#undef __GLIBC_USE_C2X_STRTOL
#define __GLIBC_USE_C2X_STRTOL 0
#undef __GLIBC_USE_C23_STRTOL
#define __GLIBC_USE_C23_STRTOL 0
#endif
