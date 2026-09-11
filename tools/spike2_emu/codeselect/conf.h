/* conf.h - images.conf, the last-choice file and the choice file.
 *
 * images.conf v2 (one image per line, index = order, 0-based):
 *   # comment
 *   image=<device>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]
 *   group=[+]<members>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]
 *                            several images shown as ONE card; confirming it
 *                            boots one member at random (item 106).  <members>
 *                            is 0-based image indexes as a range and/or a list
 *                            ('3-5', '3,5,7-9'); the rest of the line is a
 *                            card's display fields, exactly as an image line
 *                            carries them.  The line is written immediately
 *                            before its first member and the card sits in the
 *                            menu where the line sits.  Members are ordinary
 *                            image= lines and keep their image indexes, so
 *                            select.sh and the choice file are untouched.
 *                            A LEADING '+' KEEPS THE MEMBERS VISIBLE: they get
 *                            their own cards as well as the group's, so one
 *                            card can offer "surprise me" beside the very
 *                            builds it rolls between (David, 2026-09-10:
 *                            "what if i want RANDOM|CUSTOM1|CUSTOM2?").
 *                            Without it a group CONSUMES its members, which is
 *                            the forty-variant jukebox and stays the default.
 *   default=<index>          highlight when there is no usable last-choice file
 *                            (an IMAGE index; a member highlights its group's
 *                            card, unless that member keeps a card of its own)
 *   default_card=<index>     highlight this CARD instead, 0-based in menu
 *                            order.  THE ONLY WAY TO NAME A KEEPING GROUP'S
 *                            CARD: once its members keep cards of their own,
 *                            no image index resolves to the group, and a
 *                            random card the countdown cannot land on is
 *                            useless for an unattended power-up - which is the
 *                            whole point of the card.  Wins over default=.
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
 * A GROUP IS NEVER FATAL.  A member index naming no image line is dropped, a
 * group left with no member is dropped, an image named by two groups belongs
 * to the first, and image 0 is a member only in a KEEPING group - in a
 * consuming one the primary would lose its card, and the primary is what the
 * machine boots when the menu is not honoured.  Each of those is recorded in conf.warn[] for
 * the caller to log.  Only the LIMITS below refuse a file, exactly as too
 * many image lines always has.
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

/* THREE limits, because a group card makes images and cards different things.
 *
 *   CONF_MAX_IMAGES  image= lines, which are the trees on the card.  A group
 *                    of 40 song-set variants is 40 of these behind ONE card,
 *                    so this is the number item 106 raised.
 *   CONF_MAX_CARDS   what the menu draws and what the player scrolls through:
 *                    ungrouped images plus groups.  Every per-card array in
 *                    codeselect.c is sized off this one.
 *   CONF_MAX_GROUPS  group= lines.
 *
 * CONF_MAX_CARDS is overridable from the command line ONLY so `make check`
 * can build a second binary past 32 and prove the animation tick has no width
 * limit any more (item 105); a card is built against the defaults and
 * mkmulticard.py's MAX_IMAGES / MAX_CARDS / MAX_GROUPS must match them. */
#ifndef CONF_MAX_IMAGES
#define CONF_MAX_IMAGES 64
#endif
#ifndef CONF_MAX_CARDS
#define CONF_MAX_CARDS 16
#endif
#ifndef CONF_MAX_GROUPS
#define CONF_MAX_GROUPS 8
#endif
#define CONF_STR 200

/* dropped members, dropped groups and the like: never fatal, so they are
 * collected here and the caller logs them */
#define CONF_MAX_WARN 16
#define CONF_WARN_STR 200

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

/* A GROUP CARD.  `card` is what the menu draws - the same seven display
 * fields an image line carries, so every drawing path takes one of these and
 * neither knows nor cares which kind of card it came from; `card.device` is
 * unused, because a group boots whichever member the roll picks. */
struct conf_group {
    struct conf_image card;
    int member[CONF_MAX_IMAGES];
    int nmember;
    /* the members keep their own cards too ('+' on the member spec) */
    int keep;
};

/* ONE ENTRY PER THING THE MENU DRAWS, in conf-file line order.  Exactly one
 * of the two is >= 0. */
struct conf_card {
    int image;    /* a plain card: the image it boots */
    int group;    /* a group card: the group it draws and rolls from */
};

struct conf {
    struct conf_image img[CONF_MAX_IMAGES];
    int n;
    struct conf_group grp[CONF_MAX_GROUPS];
    int ngroups;
    struct conf_card cards[CONF_MAX_CARDS];
    int ncards;
    short card_of[CONF_MAX_IMAGES];  /* the card each image belongs to */
    char warn[CONF_MAX_WARN][CONF_WARN_STR];
    int nwarn;                       /* may exceed CONF_MAX_WARN: the count is honest, the text is capped */
    int def;          /* default=  (-1 when absent) */
    int def_card;     /* default_card=  (-1 when absent); wins over def */
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

/* 1 when any CARD names art or an animation (the art layout is used) */
int conf_has_art(const struct conf *c);

/* THE CARD ACCESSORS.  Everything visual walks cards through these; only the
 * boot decision and the two index files still speak in images. */

/* what card `k` draws: its own fields for a plain card, the group's for a
 * group card.  Never NULL for 0 <= k < c->ncards. */
const struct conf_image *conf_card_face(const struct conf *c, int k);

/* the card image `i` belongs to, or -1 when the index names no image.  A
 * member's card is its GROUP's, which is how a remembered member re-highlights
 * the jukebox card. */
int conf_card_of_image(const struct conf *c, int i);

/* the image card `k` boots, or -1 when it is a group and the caller must roll */
int conf_card_boots(const struct conf *c, int k);

/* how many images card `k` can boot (1 for a plain card), and the m'th of
 * them (-1 when out of range) */
int conf_card_nmembers(const struct conf *c, int k);
int conf_card_member(const struct conf *c, int k, int m);

/* The last-choice file holds one line "<index>\n". -1 when missing/invalid. */
int conf_read_last(const char *path);
int conf_write_last(const char *path, int idx);      /* 0 ok */

/* The choice file: "<index>\n", written atomically (tmp + rename). 0 ok. */
int conf_write_choice(const char *path, int idx);

#endif
