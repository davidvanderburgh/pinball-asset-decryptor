/* log.h - codeselect's two output channels.
 *
 *   sel_log()  diagnostics: stderr always, plus the --log file when one is
 *              open (appended, one line per call, with a monotonic timestamp).
 *   sel_say()  the rig-facing lines: stdout, prefixed '[select] ', and ALSO
 *              copied into the log file so a hardware run's log holds the
 *              whole story (menu / key / chose / error).
 */
#ifndef CODESELECT_LOG_H
#define CODESELECT_LOG_H

int  sel_log_open(const char *path);      /* 0 ok, -1 could not open (stderr still works) */
void sel_log_close(void);
void sel_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void sel_say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
/* CLOCK_MONOTONIC in milliseconds. long long, NOT long: armhf's long is 32
 * bits and tv_sec * 1000 wraps after 24.86 days of uptime - a WSL2 VM runs
 * that long, and every deadline compare would then go backwards. Everything
 * that holds or compares one of these is long long. */
long long sel_now_ms(void);
void sel_sleep_ms(long ms);

#endif
