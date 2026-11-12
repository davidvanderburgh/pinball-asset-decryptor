/* s3vid.h - the Spike 3 video packet feed (PAD-1090, stage 5).
 *
 * The Spike 3 game decodes its clips itself, through libavcodec, out of its
 * own packed asset store (a custom AVIO context - there is no file a host
 * decoder could open). On the Pi 4 the decoder is the V4L2 hardware HEVC
 * block and every frame is a DRM-PRIME dma-buf the game wraps as an EGL
 * image; neither exists here, and HEVC in software under qemu would crawl.
 *
 * So s3vid.c (guest, LD_PRELOAD) takes the game's HEVC/H.264 decoder
 * contexts over at the libavcodec API: avcodec_send_packet hands the
 * compressed packet to THIS feed, s3vidhost.py (host) decodes it natively
 * with ffmpeg and writes I420 frames into the Spike 2 video ring
 * (../spike2_emu/padvid.h - the layout padglhost already uploads from with
 * PADGL_TEXDIRECT), and avcodec_receive_frame hands the game a DRM-PRIME
 * frame whose dma-buf fd stands for that ring slot. Not one pixel crosses the
 * emulated CPU.
 *
 * The two files, per rig slot: s3vid.feed (this layout) and padvid.shm (the
 * frames). Both are bound into the chroot under /run.
 *
 * LAYOUT RULES as padvid.h's: u32 little-endian fields, append only. Each
 * channel's packet ring is single producer (guest: pkt_w, data_w) / single
 * consumer (host: pkt_r, data_r). The handshakes are generation counters:
 * the guest bumps *_gen, the host copies it into *_ack when served.
 */
#ifndef S3VID_H
#define S3VID_H

#define S3VID_MAGIC    0x44495653u      /* 'SVID' */
#define S3VID_VERSION  1
#define S3VID_CHANNELS 8                /* = PADVID_CHANNELS: channel c is padvid channel c */
#define S3VID_PKTS     256              /* packet descriptors per channel */
#define S3VID_DATA     (8u << 20)       /* packet bytes per channel, circular */
#define S3VID_EXTRA    4096             /* codec extradata (hvcC / avcC / Annex B) */
#define S3VID_PATH     256              /* a clip's file name (PAD-1183) */
#define S3VID_HDR      (1u << 20)       /* header block; channel data follows */
#define S3VID_BYTES    (S3VID_HDR + S3VID_CHANNELS * S3VID_DATA)

#define S3VID_PKT_KEY  1u               /* AV_PKT_FLAG_KEY */
#define S3VID_PKT_EOF  0x80000000u      /* no data: the stream is drained */

struct s3vid_pkt {
    unsigned pos;                       /* data_w at the packet: mod S3VID_DATA is where */
    unsigned size;
    unsigned pts_lo, pts_hi;            /* the packet's pts (or dts), for logging */
    unsigned flags;
    unsigned pad;
};

struct s3vid_chan {
    /* guest: a new stream. The guest fills codec..extra, sets padvid read_idx
     * to 0, bumps open_gen and waits for open_ack before its first packet. */
    unsigned open_gen, open_ack;
    unsigned codec_id;                  /* AVCodecID: 173 HEVC, 27 H264 */
    unsigned width, height;
    unsigned extra_size;
    /* guest: avcodec_flush_buffers. The host restarts the decoder, drops the
     * frames the guest has not taken (padvid write_idx = flush_base) and acks.
     * The guest waits for the ack, so no packet crosses a flush. */
    unsigned flush_gen, flush_ack, flush_base;
    unsigned closed;                    /* guest: 1 = the context is gone */
    unsigned pkt_w;                     /* guest: packets written, monotonic */
    unsigned pkt_r;                     /* host: packets consumed, monotonic */
    unsigned data_w;                    /* guest: bytes written, monotonic */
    unsigned data_r;                    /* host: bytes consumed, monotonic */
    unsigned frames_out;                /* host: frames decoded, for the log */
    /* guest, before open_gen (PAD-1183): the clip's frame count and rate off
     * its container (avformat_find_stream_info), 0 = unknown; its file is
     * clip[c] below. The host names the clip in padvid.log for the virtual
     * playfield's CLIPS list. */
    unsigned clip_frames, clip_rate_num, clip_rate_den;
    unsigned pad[14];
    unsigned char extra[S3VID_EXTRA];
    struct s3vid_pkt pkt[S3VID_PKTS];
};

struct s3vid_feed {
    unsigned magic, version;
    unsigned host_alive;                /* host bumps it while it serves */
    unsigned session;                   /* host: nonzero, new each run (PAD-1147):
                                         * a guest brought back from a save state
                                         * finds it changed and re-opens its
                                         * streams on this run's rings */
    struct s3vid_chan ch[S3VID_CHANNELS];
    /* guest, before open_gen (PAD-1183): the file channel c's clip is read
     * from, as the game has it open ("/games/<title>/.../scene.assets/2.asset
     * /247.asset"), "" when it could not be told */
    char clip[S3VID_CHANNELS][S3VID_PATH];
};

typedef char s3vid_hdr_fits[(int)(S3VID_HDR - (int)sizeof(struct s3vid_feed))];

#endif
