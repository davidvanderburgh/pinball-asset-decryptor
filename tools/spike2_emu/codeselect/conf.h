/* conf.h - images.conf, the last-choice file and the choice file.
 *
 * images.conf v2 (one image per line, index = order, 0-based):
 *   # comment
 *   image=<device>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]
 *   default=<index>          highlight when there is no usable last-choice file
 *   timeout=<seconds>        0 = wait for ever
 *   font=<path>              optional TrueType font
 *   media=<dir>              where the media names resolve (default
 *                            /usr/local/codeselect/media; --media overrides)
 *   sound_move=<wav>         played on every LEFT/RIGHT/-/+ edge
 *   sound_confirm=<wav>      played to completion on START/Select, for every
 *                            image that does not name a <confirm> of its own
 *   volume=<0-100>|machine   software mix gain (default 50), or 'machine' = the
 *                            machine's own MASTER VOLUME SETTING, read off the
 *                            card's /data/nv mirror (nvm.h); --volume still wins
 *   machine_volume=<dir>|<sha1 hex>|<0-63>  with volume=machine: the store
 *                            (/data/nv/<title>/NVM), the record's key, and the
 *                            title's factory level for a machine with no store yet
 *   mixer_volume=<0-63>      optional: apply the game's codec curve to the
 *                            ALSA 'PCM' selem (hardware only; untouched when absent)
 *   theme=<name>             the menu's colours: a built-in theme (themes.json;
 *                            the default is 'midnight') or 'custom'
 *   color_<role>=RRGGBB      one colour on top of the theme (the roles are in
 *                            themes.json); a bad value is counted and ignored
 *
 * <device> is the block device on hardware ('/dev/mmcblk0p3', '/dev/mmcblk0p7',
 * or '/dev/mmcblk0p7:img2' = a partition plus a subdirectory holding a whole
 * games tree) and an opaque token in the emulator (p3, p7, p7:img2). Titles
 * and subtitles are free UTF-8 text. Fields 4-7 are media FILE NAMES relative
 * to the media directory (empty = none); 3-field and 6-field lines stay valid.
 * Field 7 is that image's OWN confirm sound: empty or absent falls back to the
 * menu-wide sound_confirm=. Unknown keys are ignored so the file can grow.
 */
#ifndef CODESELECT_CONF_H
#define CODESELECT_CONF_H

#include "theme.h"

#define CONF_MAX_IMAGES 16
#define CONF_STR 200

struct conf_image {
    char device[CONF_STR];
    char title[CONF_STR];
    char subtitle[CONF_STR];
    char art[CONF_STR];       /* still picture (PNG), or "" */
    char anim[CONF_STR];      /* animated GIF, or "" */
    char music[CONF_STR];     /* WAV looped while highlighted, or "" */
    char confirm[CONF_STR];   /* WAV played when THIS image is confirmed, or
                               * "" = use the menu-wide sound_confirm */
};

struct conf {
    struct conf_image img[CONF_MAX_IMAGES];
    int n;
    int def;          /* default=  (-1 when absent) */
    int timeout;      /* timeout=  (-1 when absent) */
    char font[CONF_STR];
    char media[CONF_STR];          /* media= ("" when absent) */
    char sound_move[CONF_STR];     /* "" when absent */
    char sound_confirm[CONF_STR];  /* "" when absent */
    int volume;        /* volume= 0..100 (-1 when absent; the program defaults to 50) */
    int volume_machine;            /* volume=machine: follow the machine's own setting */
    char mv_store[CONF_STR];       /* machine_volume= the store dir ("" when absent)... */
    unsigned char mv_key[20];      /* ...the record's SHA1 key... */
    int mv_key_set;                /* ...(1 when a valid one was given)... */
    int mv_default;                /* ...and the title's factory level (-1 when absent) */
    int mixer_volume;  /* mixer_volume= 0..63 (-1 when absent = leave the mixer alone) */
    char theme[CONF_STR];          /* theme= ("" when absent = the default) */
    unsigned color[TH_N];          /* color_<role>= overrides... */
    unsigned char color_set[TH_N]; /* ...and which roles the conf set */
    int bad_colors;    /* color_ keys with an unknown role or a value that is not RRGGBB: ignored, counted */
};

/* 0 ok (c->n >= 1), -1 error with a message in err. */
int conf_load(struct conf *c, const char *path, char *err, int errlen);

/* 1 when any image names art or an animation (the art layout is used) */
int conf_has_art(const struct conf *c);

/* The last-choice file holds one line "<index>\n". -1 when missing/invalid. */
int conf_read_last(const char *path);
int conf_write_last(const char *path, int idx);      /* 0 ok */

/* The choice file: "<index>\n", written atomically (tmp + rename). 0 ok. */
int conf_write_choice(const char *path, int idx);

#endif
