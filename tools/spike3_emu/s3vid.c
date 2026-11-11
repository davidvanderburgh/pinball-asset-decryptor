/* s3vid.c - the Spike 3 game's video decoder, decoded on the host
 * (PAD-1090, stage 5).
 *
 * LD_PRELOAD (aarch64) into the card's own game, beside s3kms.so. See s3vid.h
 * for the why. The game (Stern's Radium, FFmpeg 5.1.6-rpi: libavcodec
 * 59.37.100 - this builds against those exact headers) decodes each clip with
 *     avcodec_open2 -> { avcodec_send_packet ; avcodec_receive_frame }*
 *                   -> avcodec_flush_buffers (a seek) -> avcodec_free_context
 * expecting DRM-PRIME frames from the Pi 4's V4L2 HEVC block, which it wraps
 * as EGL images (EGL_LINUX_DMA_BUF_EXT) and samples. For HEVC and H.264
 * contexts those five calls are answered here:
 *
 *   open2         the real open (the context stays valid for the game) and a
 *                 channel in the packet feed: codec, size, extradata
 *   send_packet   the compressed packet into the channel's ring (EAGAIN when
 *                 the ring is full - the API's own back-pressure)
 *   receive_frame the next frame the host has put in the padvid ring, as an
 *                 AV_PIX_FMT_DRM_PRIME frame: one object, three I420 planes,
 *                 and an fd that stands for (channel, slot) - s3egl.c maps it
 *                 back (pad_s3_vid_fd) and s3gl.c turns the bind into a
 *                 PADGL_TEXDIRECT of that slot, uploaded on the host GPU
 *   flush_buffers the host restarts that decoder; frames not taken are dropped
 *   free_context  the channel is closed
 *
 * A frame's slot is only reused once the game has released the frame (its
 * AVBufferRef's free callback advances padvid read_idx, in order).
 *
 * Frame times: packets arrive in decode order and frames leave in display
 * order, so each frame takes the smallest pts not yet handed out.
 *
 * Without the host decoder (no /run/s3vid) every call goes to the real
 * libavcodec, as before. [s3vid] lines go to stderr.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include "libavcodec/avcodec.h"
#include "libavutil/hwcontext_drm.h"
#include "padvid.h"
#include "s3vid.h"

#define DRM_FORMAT_YUV420 0x32315559u   /* 'YU12' */
#define MAXPTS 128

static struct s3vid_feed *feed;
static struct padvid_shm *vshm;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static int tried;

static struct stream {
    AVCodecContext *ctx;
    unsigned handed;                    /* frames given to the game */
    unsigned released[64];              /* by frame number % 64: freed */
    unsigned eof_sent;
    int64_t pts[MAXPTS];                /* pending pts, unsorted */
    int npts;
    int64_t last_pts, step;             /* for a frame with no packet time */
    unsigned long frames, packets;
} st[S3VID_CHANNELS];

static int slot_fd[S3VID_CHANNELS][PADVID_SLOTS];

static int (*real_open2)(AVCodecContext *, const AVCodec *, AVDictionary **);
static int (*real_send)(AVCodecContext *, const AVPacket *);
static int (*real_recv)(AVCodecContext *, AVFrame *);
static void (*real_flush)(AVCodecContext *);
static void (*real_free)(AVCodecContext **);
static void (*p_frame_unref)(AVFrame *);
static AVBufferRef *(*p_buffer_create)(uint8_t *, size_t, void (*)(void *, uint8_t *), void *, int);

static void sayf(const char *fmt, long a, long b, long c)
{
    char m[200];
    int n = snprintf(m, sizeof m, fmt, a, b, c);
    if (n > 0) (void)!write(2, m, (size_t)(n < (int)sizeof m ? n : (int)sizeof m - 1));
}

static void *map(const char *path, unsigned long bytes)
{
    int fd = open(path, O_RDWR);
    void *p;
    if (fd < 0) return 0;
    p = mmap(0, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    return p == MAP_FAILED ? 0 : p;
}

static int setup(void)
{
    int c, s;
    if (tried) return feed != 0;
    tried = 1;
    real_open2 = dlsym(RTLD_NEXT, "avcodec_open2");
    real_send = dlsym(RTLD_NEXT, "avcodec_send_packet");
    real_recv = dlsym(RTLD_NEXT, "avcodec_receive_frame");
    real_flush = dlsym(RTLD_NEXT, "avcodec_flush_buffers");
    real_free = dlsym(RTLD_NEXT, "avcodec_free_context");
    p_frame_unref = dlsym(RTLD_DEFAULT, "av_frame_unref");
    p_buffer_create = dlsym(RTLD_DEFAULT, "av_buffer_create");
    feed = map("/run/s3vid", S3VID_BYTES);
    vshm = map("/run/padvid", PADVID_BYTES);
    if (!feed || !vshm || feed->magic != S3VID_MAGIC || vshm->magic != PADVID_MAGIC ||
        !p_frame_unref || !p_buffer_create) {
        sayf("[s3vid] no host decoder (feed %ld, frames %ld): the game decodes itself\n",
             (long)(feed != 0), (long)(vshm != 0), 0);
        feed = 0;
        return 0;
    }
    for (c = 0; c < S3VID_CHANNELS; c++)
        for (s = 0; s < PADVID_SLOTS; s++)
            slot_fd[c][s] = eventfd(0, EFD_CLOEXEC);
    sayf("[s3vid] host decoder attached: %ld channels x %ld slots\n",
         S3VID_CHANNELS, PADVID_SLOTS, 0);
    return 1;
}

static int chan_of(const AVCodecContext *ctx)
{
    int c;
    if (!ctx || !feed) return -1;
    for (c = 0; c < S3VID_CHANNELS; c++)
        if (st[c].ctx == ctx) return c;
    return -1;
}

static int wait_ack(volatile unsigned *ack, unsigned gen)
{
    int i;
    for (i = 0; i < 4000 && *ack != gen; i++) {     /* up to ~2 s */
        struct timespec ts = { 0, 500000 };
        nanosleep(&ts, 0);
    }
    return *ack == gen;
}

/* ---- the five calls ---------------------------------------------------- */

int avcodec_open2(AVCodecContext *ctx, const AVCodec *codec, AVDictionary **opts)
{
    int r, c;
    if (!tried) setup();
    if (!real_open2) real_open2 = dlsym(RTLD_NEXT, "avcodec_open2");
    r = real_open2(ctx, codec, opts);
    if (!feed || !ctx ||
        (ctx->codec_id != AV_CODEC_ID_HEVC && ctx->codec_id != AV_CODEC_ID_H264))
        return r;
    /* The real open of the Pi's hardware decoders FAILS here - the game asks
     * for h264_v4l2m2m by name and there is no V4L2 device ("Could not find
     * a valid device") - and passing that on is "InitCodecContext failed" on
     * every H.264 clip. The real decoder is never used on these contexts:
     * the host decodes them, so the open succeeds regardless. */
    if (r < 0) {
        sayf("[s3vid] the real %s open failed (%ld): decoded on the host anyway\n",
             (long)(codec && codec->name ? codec->name : "decoder"), r, 0);
        r = 0;
    }
    pthread_mutex_lock(&mu);
    for (c = 0; c < S3VID_CHANNELS; c++)
        if (!st[c].ctx) break;
    if (c == S3VID_CHANNELS) {
        pthread_mutex_unlock(&mu);
        sayf("[s3vid] all %ld channels busy: this stream decodes in the guest\n", S3VID_CHANNELS, 0, 0);
        return r;
    }
    memset(&st[c], 0, sizeof st[c]);
    st[c].ctx = ctx;
    st[c].last_pts = AV_NOPTS_VALUE;
    {
        struct s3vid_chan *ch = &feed->ch[c];
        unsigned n = ctx->extradata_size > 0 ? (unsigned)ctx->extradata_size : 0;
        if (n > S3VID_EXTRA) n = S3VID_EXTRA;
        ch->codec_id = (unsigned)ctx->codec_id;
        ch->width = (unsigned)ctx->width;
        ch->height = (unsigned)ctx->height;
        ch->extra_size = n;
        if (n) memcpy(ch->extra, ctx->extradata, n);
        ch->closed = 0;
        vshm->ch[c].read_idx = 0;
        __sync_synchronize();
        ch->open_gen++;
        if (!wait_ack(&ch->open_ack, ch->open_gen)) {
            st[c].ctx = 0;
            pthread_mutex_unlock(&mu);
            sayf("[s3vid] ch%ld: the host decoder did not answer the open\n", c, 0, 0);
            return r;
        }
    }
    pthread_mutex_unlock(&mu);
    sayf("[s3vid] ch%ld: %s %ldx", c, (long)(ctx->codec_id == AV_CODEC_ID_HEVC ? "hevc" : "h264"), ctx->width);
    sayf("%ld, extradata %ld bytes - decoded on the host\n", ctx->height, ctx->extradata_size, 0);
    return r;
}

int avcodec_send_packet(AVCodecContext *ctx, const AVPacket *pkt)
{
    int c = chan_of(ctx);
    struct s3vid_chan *ch;
    struct s3vid_pkt *d;
    unsigned size, off;
    if (c < 0) {
        if (!real_send) real_send = dlsym(RTLD_NEXT, "avcodec_send_packet");
        return real_send(ctx, pkt);
    }
    ch = &feed->ch[c];
    /* A real decoder answers EAGAIN only while a decoded frame waits to be
     * read, and the game calls anything else "Unexpected busy error when
     * SENDING PACKET". So a full ring is waited out (the host drains it as
     * fast as ffmpeg takes it), and EAGAIN is the last resort. */
    {
        unsigned need = pkt && pkt->size > 0 ? (unsigned)pkt->size : 0;
        int i;
        for (i = 0; i < 2000; i++) {
            unsigned off0 = ch->data_w % S3VID_DATA;
            unsigned pad = off0 + need > S3VID_DATA ? S3VID_DATA - off0 : 0;
            if (ch->pkt_w - ch->pkt_r < S3VID_PKTS &&
                ch->data_w + pad + need - ch->data_r <= S3VID_DATA)
                break;
            {
                struct timespec ts = { 0, 1000000 };
                nanosleep(&ts, 0);
            }
        }
    }
    if (ch->pkt_w - ch->pkt_r >= S3VID_PKTS) return AVERROR(EAGAIN);
    d = &ch->pkt[ch->pkt_w % S3VID_PKTS];
    if (!pkt || !pkt->data || pkt->size <= 0) {         /* drain */
        if (st[c].eof_sent) return AVERROR_EOF;
        d->pos = ch->data_w; d->size = 0; d->flags = S3VID_PKT_EOF;
        d->pts_lo = d->pts_hi = 0;
        __sync_synchronize();
        ch->pkt_w++;
        st[c].eof_sent = 1;
        return 0;
    }
    size = (unsigned)pkt->size;
    if (size > S3VID_DATA / 2) return AVERROR(ENOMEM);
    off = ch->data_w % S3VID_DATA;
    if (off + size > S3VID_DATA) {                      /* no wrap inside a packet */
        if (ch->data_w + (S3VID_DATA - off) + size - ch->data_r > S3VID_DATA) return AVERROR(EAGAIN);
        ch->data_w += S3VID_DATA - off;
        off = 0;
    }
    if (ch->data_w + size - ch->data_r > S3VID_DATA) return AVERROR(EAGAIN);
    memcpy((unsigned char *)feed + S3VID_HDR + (unsigned long)c * S3VID_DATA + off, pkt->data, size);
    d->pos = ch->data_w; d->size = size;
    d->flags = (pkt->flags & AV_PKT_FLAG_KEY) ? S3VID_PKT_KEY : 0;
    {
        int64_t t = pkt->pts != AV_NOPTS_VALUE ? pkt->pts : pkt->dts;
        d->pts_lo = (unsigned)t; d->pts_hi = (unsigned)((uint64_t)t >> 32);
        pthread_mutex_lock(&mu);
        if (st[c].npts < MAXPTS) st[c].pts[st[c].npts++] = t;
        pthread_mutex_unlock(&mu);
    }
    ch->data_w += size;
    __sync_synchronize();
    ch->pkt_w++;
    st[c].packets++;
    return 0;
}

struct held { int c; unsigned n; };

static void release(void *opaque, uint8_t *data)
{
    struct held *h = opaque;
    struct stream *s = &st[h->c];
    pthread_mutex_lock(&mu);
    s->released[h->n % 64] = h->n + 1;
    /* read_idx follows the frames released IN ORDER: a slot is reused only
     * once every frame before it is gone too */
    while (vshm->ch[h->c].read_idx < s->handed &&
           s->released[vshm->ch[h->c].read_idx % 64] == vshm->ch[h->c].read_idx + 1)
        vshm->ch[h->c].read_idx++;
    pthread_mutex_unlock(&mu);
    free(data);
    free(h);
}

int avcodec_receive_frame(AVCodecContext *ctx, AVFrame *frame)
{
    int c = chan_of(ctx), i, best;
    volatile struct padvid_chan *v;
    unsigned w, h, slot, n;
    AVDRMFrameDescriptor *desc;
    struct held *hd;
    int64_t pts;
    if (c < 0) {
        if (!real_recv) real_recv = dlsym(RTLD_NEXT, "avcodec_receive_frame");
        return real_recv(ctx, frame);
    }
    v = &vshm->ch[c];
    if (feed->ch[c].flush_ack != feed->ch[c].flush_gen) return AVERROR(EAGAIN);
    if (v->write_idx == st[c].handed && st[c].eof_sent) {
        /* DRAINING (send_packet(NULL)): the game reads until AVERROR_EOF
         * against a short timeout of its own ("SpiVideoStreamDecoderBase::
         * FlushDecoder while loop timeout" when the end waited for the host
         * ffmpeg to exit). So: a frame still coming out gets a moment, and
         * then the end is the end. */
        int i;
        for (i = 0; i < 25 && v->write_idx == st[c].handed && !v->eos; i++) {
            struct timespec ts = { 0, 1000000 };
            nanosleep(&ts, 0);
        }
        if (v->write_idx == st[c].handed) return AVERROR_EOF;
    }
    if (v->write_idx == st[c].handed) return AVERROR(EAGAIN);
    __sync_synchronize();
    n = st[c].handed;
    slot = n % PADVID_SLOTS;
    w = v->width; h = v->height;
    desc = calloc(1, sizeof *desc);
    hd = malloc(sizeof *hd);
    if (!desc || !hd) { free(desc); free(hd); return AVERROR(ENOMEM); }
    hd->c = c; hd->n = n;
    desc->nb_objects = 1;
    desc->objects[0].fd = slot_fd[c][slot];
    desc->objects[0].size = v->frame_bytes;
    desc->objects[0].format_modifier = 0;           /* DRM_FORMAT_MOD_LINEAR */
    desc->nb_layers = 1;
    desc->layers[0].format = DRM_FORMAT_YUV420;
    desc->layers[0].nb_planes = 3;
    desc->layers[0].planes[0].offset = 0;
    desc->layers[0].planes[0].pitch = w;
    desc->layers[0].planes[1].offset = (ptrdiff_t)w * h;
    desc->layers[0].planes[1].pitch = w / 2;
    desc->layers[0].planes[2].offset = (ptrdiff_t)w * h + (ptrdiff_t)(w / 2) * (h / 2);
    desc->layers[0].planes[2].pitch = w / 2;
    p_frame_unref(frame);
    frame->buf[0] = p_buffer_create((uint8_t *)desc, sizeof *desc, release, hd, 0);
    if (!frame->buf[0]) { free(desc); free(hd); return AVERROR(ENOMEM); }
    frame->data[0] = (uint8_t *)desc;
    frame->format = AV_PIX_FMT_DRM_PRIME;
    frame->width = (int)w;
    frame->height = (int)h;
    frame->key_frame = 1;
    pthread_mutex_lock(&mu);
    pts = AV_NOPTS_VALUE;
    best = -1;
    for (i = 0; i < st[c].npts; i++)
        if (best < 0 || st[c].pts[i] < st[c].pts[best]) best = i;
    if (best >= 0) { pts = st[c].pts[best]; st[c].pts[best] = st[c].pts[--st[c].npts]; }
    /* A frame with no pending packet time (one whose packet's pts went with
     * a flush): the game asserts pts != AV_NOPTS_VALUE (DecodeFrame, :1643),
     * so it takes the stream's own cadence - the last time plus the last step */
    if (pts == AV_NOPTS_VALUE)
        pts = st[c].last_pts != AV_NOPTS_VALUE ? st[c].last_pts + (st[c].step > 0 ? st[c].step : 1) : 0;
    if (st[c].last_pts != AV_NOPTS_VALUE && pts > st[c].last_pts)
        st[c].step = pts - st[c].last_pts;
    st[c].last_pts = pts;
    st[c].handed++;
    st[c].frames++;
    pthread_mutex_unlock(&mu);
    frame->pts = frame->best_effort_timestamp = pts;
    frame->pkt_dts = AV_NOPTS_VALUE;
    if (st[c].frames == 1 || st[c].frames % 600 == 0)
        sayf("[s3vid] ch%ld: frame %ld (%ld packets in)\n", c, (long)st[c].frames, (long)st[c].packets);
    return 0;
}

void avcodec_flush_buffers(AVCodecContext *ctx)
{
    int c = chan_of(ctx);
    struct s3vid_chan *ch;
    if (c < 0) {
        if (!real_flush) real_flush = dlsym(RTLD_NEXT, "avcodec_flush_buffers");
        real_flush(ctx);
        return;
    }
    ch = &feed->ch[c];
    pthread_mutex_lock(&mu);
    st[c].npts = 0;
    st[c].eof_sent = 0;
    st[c].last_pts = AV_NOPTS_VALUE;           /* a seek: time starts over */
    ch->flush_base = st[c].handed;
    __sync_synchronize();
    ch->flush_gen++;
    pthread_mutex_unlock(&mu);
    if (!wait_ack(&ch->flush_ack, ch->flush_gen))
        sayf("[s3vid] ch%ld: the host decoder did not answer a flush\n", c, 0, 0);
}

void avcodec_free_context(AVCodecContext **pctx)
{
    int c = pctx ? chan_of(*pctx) : -1;
    if (c >= 0) {
        pthread_mutex_lock(&mu);
        feed->ch[c].closed = 1;
        st[c].ctx = 0;
        pthread_mutex_unlock(&mu);
    }
    if (!real_free) real_free = dlsym(RTLD_NEXT, "avcodec_free_context");
    real_free(pctx);
}

/* ---- for s3egl.c / s3gl.c ---------------------------------------------- */

/* A dma-buf fd this file handed out: its image id (channel * SLOTS + slot)
 * plus one, or 0. */
unsigned pad_s3_vid_fd(int fd)
{
    int c, s;
    if (!feed || fd < 0) return 0;
    for (c = 0; c < S3VID_CHANNELS; c++)
        for (s = 0; s < PADVID_SLOTS; s++)
            if (slot_fd[c][s] == fd) return (unsigned)(c * PADVID_SLOTS + s) + 1;
    return 0;
}

/* What a video image (id from pad_s3_vid_fd, minus one) holds now: its byte
 * offset in the padvid ring, size and length. 0 if the channel has no frame. */
int pad_s3_vid_image(unsigned id, unsigned *off, unsigned *w, unsigned *h, unsigned *bytes)
{
    unsigned c = id / PADVID_SLOTS, s = id % PADVID_SLOTS;
    volatile struct padvid_chan *v;
    if (!feed || c >= S3VID_CHANNELS) return 0;
    v = &vshm->ch[c];
    if (!v->width || !v->height || !v->frame_bytes) return 0;
    *off = c * PADVID_SLOTS * PADVID_SLOT_BYTES + s * PADVID_SLOT_BYTES;
    *w = v->width; *h = v->height; *bytes = v->frame_bytes;
    return 1;
}
