/* conf.h - images.conf, the last-choice file and the choice file.
 *
 * images.conf (one image per line, index = order, 0-based):
 *   # comment
 *   image=<device>|<title>|<subtitle>
 *   default=<index>          highlight when there is no usable last-choice file
 *   timeout=<seconds>        0 = wait for ever
 *   font=<path>              optional TrueType font
 *
 * <device> is the block device on hardware (/dev/mmcblk0p3 ...) and an opaque
 * token in the emulator (p3, p7). Titles/subtitles are free text (UTF-8).
 */
#ifndef CODESELECT_CONF_H
#define CODESELECT_CONF_H

#define CONF_MAX_IMAGES 8
#define CONF_STR 200

struct conf_image {
    char device[CONF_STR];
    char title[CONF_STR];
    char subtitle[CONF_STR];
};

struct conf {
    struct conf_image img[CONF_MAX_IMAGES];
    int n;
    int def;          /* default=  (-1 when absent) */
    int timeout;      /* timeout=  (-1 when absent) */
    char font[CONF_STR];
};

/* 0 ok (c->n >= 1), -1 error with a message in err. */
int conf_load(struct conf *c, const char *path, char *err, int errlen);

/* The last-choice file holds one line "<index>\n". -1 when missing/invalid. */
int conf_read_last(const char *path);
int conf_write_last(const char *path, int idx);      /* 0 ok */

/* The choice file: "<index>\n", written atomically (tmp + rename). 0 ok. */
int conf_write_choice(const char *path, int idx);

#endif
