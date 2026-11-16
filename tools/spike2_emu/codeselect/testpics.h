/* testpics.h - the TEST PICTURES screen's built-in patterns (PAD-1279).
 *
 * Settings > Test pictures shows, full screen and pixel for pixel, first
 * these patterns - drawn here, so every card has them with no file at all -
 * and then the pictures, animations and sounds the card was built with
 * (images.conf test= lines).  Each is drawn through the colour correction
 * the operator picks, the same numbers the Color correction screen moves,
 * so a profile can be judged on the real screen with no build in between.
 *
 * The patterns are what a screen is judged by: the PAD test card (the Color
 * profile tab's, colour.h), a grey ramp with the darkest and lightest steps
 * apart, smooth colour ramps, one- and two-pixel lines and checks with a
 * one-pixel border round the whole picture (scaling, sharpness, overscan),
 * and full white and full black.
 */
#ifndef CODESELECT_TESTPICS_H
#define CODESELECT_TESTPICS_H

enum { TP_CARD, TP_GREY, TP_COLOURS, TP_SHARP, TP_WHITE, TP_BLACK, TP_NBUILTIN };

/* the pattern's name on the screen, and the one line saying what to look for */
const char *testpics_name(int k);
const char *testpics_hint(int k);

/* Draw pattern k over the whole w x h RGBA canvas (top-down rows, stride
 * bytes apart).  An unknown k draws black. */
void testpics_draw(int k, unsigned char *px, int stride, int w, int h);

/* What a test= file is, from its name: TF_PICTURE (.png), TF_ANIM (.gif),
 * TF_SOUND (.wav), TF_VIDEO (.padv, video.h), else TF_UNKNOWN. */
enum { TF_UNKNOWN, TF_PICTURE, TF_ANIM, TF_SOUND, TF_VIDEO };
int testpics_kind(const char *file);

#endif
