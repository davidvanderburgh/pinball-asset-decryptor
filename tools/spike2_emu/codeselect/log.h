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
long sel_now_ms(void);                    /* CLOCK_MONOTONIC in milliseconds */
void sel_sleep_ms(long ms);

#endif
