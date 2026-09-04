/* input.c - the shared debouncer and event queue (see input.h) */
#define _GNU_SOURCE
#include <string.h>
#include "input.h"

void input_base_init(struct input *in, const struct input_ops *ops)
{
    int k;
    memset(in, 0, sizeof *in);
    in->ops = ops;
    pthread_mutex_init(&in->lock, NULL);
    for (k = 0; k < KEY_COUNT; k++) {
        in->last[k] = -1;
        in->stable[k] = -1;          /* unknown until two samples agree */
        in->present[k] = 1;          /* possible until a backend says it is not */
    }
}

static void queue(struct input *in, int ev)
{
    int next;
    pthread_mutex_lock(&in->lock);
    next = (in->evw + 1) % 32;
    if (next != in->evr) {           /* full: drop */
        in->evq[in->evw] = ev;
        in->evw = next;
    }
    pthread_mutex_unlock(&in->lock);
}

void input_sample(struct input *in, int key, int pressed)
{
    if (key < 0 || key >= KEY_COUNT) return;
    pressed = pressed ? 1 : 0;
    if (pressed == in->last[key]) {
        if (in->count[key] < 1000) in->count[key]++;
    } else {
        in->last[key] = pressed;
        in->count[key] = 1;
    }
    if (in->count[key] < 2) return;
    if (in->stable[key] < 0) {       /* first settled level: no edge */
        in->stable[key] = pressed;
        return;
    }
    if (pressed != in->stable[key]) {
        in->stable[key] = pressed;
        if (pressed) queue(in, key + 1);
    }
}

int input_poll(struct input *in, long long now_ms)
{
    int ev = EV_NONE;
    if (!in) return EV_NONE;
    if (!in->threaded && in->ops && in->ops->poll) in->ops->poll(in, now_ms);
    pthread_mutex_lock(&in->lock);
    if (in->evr != in->evw) {
        ev = in->evq[in->evr];
        in->evr = (in->evr + 1) % 32;
    }
    pthread_mutex_unlock(&in->lock);
    return ev;
}

int input_has(const struct input *in, int ev)
{
    if (!in || ev <= EV_NONE || ev >= EV_COUNT) return 0;
    return in->present[KEY_OF(ev)];
}

void input_close(struct input *in)
{
    if (in && in->ops && in->ops->close) in->ops->close(in);
}

const char *input_event_name(int ev)
{
    static const char *names[EV_COUNT] = {
        "none", "left", "right", "start", "action", "select", "plus", "minus", "back"
    };
    if (ev < 0 || ev >= EV_COUNT) return "?";
    return names[ev];
}
