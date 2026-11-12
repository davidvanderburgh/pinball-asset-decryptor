/* scores.h - one high-score table shared by images that keep their own
 * settings (PAD-1194).
 *
 * pb_lawww (Pinside, 2026-11): "would it be possible to separate 'own
 * highscores' and 'own settings' for multiboot?" - an Original image with
 * everything of its own, and two Heisei images with their own settings but
 * one high-score table between them.
 *
 * WHERE THE TABLE LIVES.  A Spike 2 game keeps /data/nv/<title>/ as eight
 * stores, each a directory of generations named "%08d" (the greatest name is
 * the newest) with a <name>.crc32 sidecar (zlib CRC32 of the file, LE).  The
 * game plays from LKRAM: an 'NFI2' file holding one 'NSEC' section (+12 =
 * CRC32 of everything from +20 to the end) of named blocks, each
 *
 *   tag[4] ('NDAT' | 'NMEM') | len u32 (bytes after this field) | id u32 | ...
 *
 * and on every Spike 2 title the rig's stores hold (read 2026-11-12) the blocks are
 * replay_data, redemption_block, the adjustments (id 0xedfea13d, value/check
 * pairs), the audits (0x242b9532), THE HIGH SCORES (0xee0420dd: element size
 * u32, count u32, then count rows of 96 bytes - 88 on the oldest titles -
 * initials +32, score +72, check +88) and three small ones.  NVM keeps a
 * keyed copy for version migration; the live table is LKRAM's: a generation
 * whose score block alone was changed showed the changed grand champion in
 * attract, everything else as it was (emulator, Godzilla LE 1.16).
 *
 * So the selector hands over that one block and nothing else: the images
 * keep their own settings, audits and the rest of LKRAM.  The boot hook
 * saves the block of the store that booted LAST into the group's file
 * (--scores-save) and loads the group's file into the store about to boot
 * (--scores-load), which writes it as a NEW LKRAM generation.  Every failure
 * leaves the store as the game left it. */
#ifndef CODESELECT_SCORES_H
#define CODESELECT_SCORES_H

#define SCORES_BLOCK_ID 0xee0420ddu

/* The newest good LKRAM generation in <store>/LKRAM -> its score block,
 * written to <to> (via <to>.part).  0 = saved, 1 = nothing to save (no
 * LKRAM yet, or none that reads), 2 = refused (cannot write).  msg says
 * what happened either way. */
int scores_save(const char *store, const char *to, char *msg, int msglen);

/* <from>'s block -> a new LKRAM generation in <store>/LKRAM, the newest
 * good one with only its score block replaced.  0 = written, 1 = nothing
 * to do (no file, no LKRAM yet, or the table is already that one), 2 =
 * refused (a block of another size or row length: another game version). */
int scores_load(const char *from, const char *store, char *msg, int msglen);

#endif
