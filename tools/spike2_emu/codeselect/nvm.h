/* nvm.h - the machine's own settings, read off the card's /data/nv mirror.
 *
 * Spike 2 keeps the operator settings on the board and mirrors them to the
 * card at /data/nv/<title>/NVM/<generation> (a ring of three; the highest
 * name is the newest).  The body is Stern's .SPB export byte for byte:
 * 'MAP0' + map code, u16 counts at 0x3c (audits) and 0x3e (adjustments),
 * 40-byte audit records from offset 208, then 44-byte adjustment records:
 *
 *   SHA1(menu caption)[20] | default u32 | min u32 | max u32 | id u32
 *   | LIVE VALUE u32 | check u32 (= 0xFF - (value & 0xff))
 *
 * The key is the SHA1 of the caption the menu shows, so it is the same on
 * every version of a title and the tools hand it over in images.conf
 * (machine_volume=<store>|<sha1 hex>|<default>) - nothing here hashes.
 *
 * David, 2026-09-03: "we need to be considerate of what volume level it
 * will play at on the actual machine. it should follow the set volume of
 * the actual machine."  The record read is MASTER VOLUME SETTING (0-63).
 */
#ifndef CODESELECT_NVM_H
#define CODESELECT_NVM_H

/* Read the live value of the adjustment keyed by key[20] from the newest
 * store in dir (a directory of generation files).  0 and *value on success;
 * -1 with the reason in why (dir missing, no store, no such record, a bad
 * check).  from (may be NULL) gets the file the value came from. */
int nvm_read_value(const char *dir, const unsigned char key[20], int *value,
                   char *from, int fromlen, char *why, int whylen);

/* 40 hex characters -> 20 bytes; 0 ok, -1 not hex */
int nvm_parse_key(const char *hex, unsigned char key[20]);

#endif
