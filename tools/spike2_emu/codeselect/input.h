/* input.h - the menu's buttons, from one of two backends.
 *
 *   hw     the machine: node bus 0x11 scans of node 8 (flippers) and node 1
 *          (START, bit 11, and the lockdown-bar Action button, bit 2 - one
 *          reply carries both) over /dev/ttymxc1, plus the node-0 cabinet
 *          word over /dev/spidev1.0 (Service Select/Plus/Minus/Back).
 *   padsw  the emulator: the rig's keyboard channel file (PAD_SW_SHM),
 *          switch ids resolved from the title's switch_list.txt.
 *
 * Both backends sample raw levels and feed input_sample(); the shared
 * debouncer turns two agreeing samples into a state and each press edge into
 * one event. Releases produce no event.
 *
 * EV_ACTION is the button on the lockdown bar ("Action Button" on the newer
 * lists, "LOCKDOWN BUTTON" on the older ones). It is its own event so the
 * '[select] key:' line names the button that was actually pressed; the menu
 * treats it exactly as EV_START.
 */
#ifndef CODESELECT_INPUT_H
#define CODESELECT_INPUT_H

enum sel_event {
    EV_NONE = 0,
    EV_LEFT, EV_RIGHT, EV_START, EV_ACTION, EV_SELECT, EV_PLUS, EV_MINUS, EV_BACK,
    EV_COUNT
};
#define KEY_COUNT (EV_COUNT - 1)      /* keys are events minus EV_NONE */
#define KEY_OF(ev) ((ev) - 1)

struct input_cfg {
    const char *nodebus;      /* hw: tty device */
    const char *spi;          /* hw: spidev, or "none" */
    int preamble_full;        /* hw: also replay the game's write-only frames */
    const char *padsw;        /* padsw: the 4096-byte shared file */
    const char *tables;       /* padsw: switch_list.txt, may be missing */
};

struct input;
struct input_ops {
    void (*poll)(struct input *in, long long now_ms);   /* sample, feed input_sample; now_ms = sel_now_ms() */
    void (*close)(struct input *in);
};

struct input {
    const struct input_ops *ops;
    int last[KEY_COUNT], count[KEY_COUNT], stable[KEY_COUNT];
    int evq[32];
    int evw, evr;
};

void input_base_init(struct input *in, const struct input_ops *ops);
void input_sample(struct input *in, int key, int pressed);
int  input_poll(struct input *in, long long now_ms);   /* next event or EV_NONE */
void input_close(struct input *in);
const char *input_event_name(int ev);

struct input *input_hw_open(const struct input_cfg *cfg);
struct input *input_padsw_open(const struct input_cfg *cfg);

#endif
