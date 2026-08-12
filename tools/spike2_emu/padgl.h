/* padgl.h - wire protocol between the emulated game and the native renderer.
 *
 * The game is ARM code under qemu-user and cannot reach a GPU: qemu passes
 * syscalls through but guest code cannot load a native GPU driver. So the
 * guest stub SERIALISES its GL calls into a shared-memory ring and a native
 * x86-64 helper replays them on real GLES via EGL.
 *
 * Measured facts this design rests on (see the handoff):
 *   - 2 to 4 draw calls per frame, vertex buffers of 6 to 132 indices
 *   - textures uploaded ONCE at startup, ~30 MB total
 *   - the ONLY per-frame readbacks are glGetIntegerv(GL_BLEND_SRC/DST), which
 *     the guest shadows locally, so there are NO per-frame round trips
 *   - the game's `#version 300 es` shaders compile verbatim on the host, so
 *     shader source is forwarded as-is with no translation
 *
 * Both ends are little-endian (ARM32 / x86-64). No pointers ever cross: every
 * command carries its own payload, sized in the header.
 */
#ifndef PADGL_H
#define PADGL_H

#define PADGL_MAGIC   0x4c477061u      /* "apGL" */
#define PADGL_VERSION 1

/* Ring is a byte buffer with a header at offset 0. Single producer (guest),
 * single consumer (host). head/tail are free-running byte counters; the
 * modulo is taken on use, so wrap needs no special case beyond the split copy. */
typedef struct {
    unsigned int  magic;
    unsigned int  version;
    unsigned int  ring_bytes;      /* size of the data area that follows      */
    unsigned int  guest_alive;
    unsigned long long head;       /* producer: bytes written                 */
    unsigned long long tail;       /* consumer: bytes read                    */
    unsigned long long frame_seq;  /* producer: frames submitted              */
    unsigned long long frame_ack;  /* consumer: frames completed              */
    unsigned int  fb_w, fb_h;
    unsigned int  host_ready;
    unsigned int  host_error;
    /* ★ ITEM 43: HOST->GUEST. Two bits, so the guest can tell "not in the
     * menu" from "nobody is watching":
     *   bit 1 (ARMED) - a padglhost with the menu detector is alive and
     *                   classifying draws (PAD_GL_MENUPROG nonzero);
     *   bit 0 (MENU)  - the renderer currently sees the game drawing the
     *                   SERVICE MENU (frames whose only draws use the menu
     *                   page-type's program - 27 on turtles 4.28).
     * So: 0 = old binary or disarmed detector (guest FALLS BACK to the door
     * gate), 2 = armed + not menu, 3 = armed + in menu. Written by padglhost
     * at draw/SWAP time; read by the guest video shim (gstvid) as the "in
     * the menu" gate that replaces the flicker-prone coin-door read.
     * Appended AFTER host_error on purpose: the ring data starts at the
     * fixed PADGL_HDR_BYTES page boundary, so old binaries and new agree on
     * every other field and an old reader simply never looks at this one. */
    unsigned int  menu_flag;
} padgl_hdr;

#define PADGL_HDR_BYTES  4096          /* header page, then the ring data */

/* Every command: [u32 op][u32 len] then len bytes of payload, 8-byte aligned. */
typedef struct { unsigned int op, len; } padgl_cmd;

enum {
    PADGL_NOP = 0,
    PADGL_SWAP,                 /* end of frame                                */
    PADGL_VIEWPORT,             /* i32 x,y,w,h                                 */
    PADGL_CLEARCOLOR,           /* f32 r,g,b,a                                 */
    PADGL_CLEAR,                /* u32 mask                                    */
    PADGL_ENABLE,               /* u32 cap                                     */
    PADGL_DISABLE,              /* u32 cap                                     */
    PADGL_BLENDFUNC,            /* u32 src,dst                                 */
    PADGL_BLENDFUNCSEP,         /* u32 srgb,drgb,sa,da                         */
    PADGL_BLENDEQ,              /* u32 mode                                    */
    PADGL_BLENDEQSEP,           /* u32 rgb,a                                   */
    PADGL_SCISSOR,              /* i32 x,y,w,h                                 */

    PADGL_GENTEX,               /* u32 name  (guest allocates, host mirrors)   */
    PADGL_BINDTEX,              /* u32 target,name                             */
    PADGL_ACTIVETEX,            /* u32 unit                                    */
    PADGL_TEXIMAGE,             /* u32 lvl,ifmt,w,h,fmt,type + pixels          */
    PADGL_TEXSUBIMAGE,          /* u32 lvl,x,y,w,h,fmt,type + pixels           */
    PADGL_TEXCOMPRESSED,        /* u32 lvl,ifmt,w,h,size + data                */
    PADGL_TEXPARAM,             /* u32 target,pname,param                      */
    PADGL_DELTEX,               /* u32 name                                    */

    PADGL_GENBUF,               /* u32 name                                    */
    PADGL_BINDBUF,              /* u32 target,name                             */
    PADGL_BUFDATA,              /* u32 target,usage,size + data                */
    PADGL_BUFSUBDATA,           /* u32 target,offset,size + data               */
    PADGL_DELBUF,               /* u32 name                                    */

    PADGL_GENVAO,               /* u32 name                                    */
    PADGL_BINDVAO,              /* u32 name                                    */
    PADGL_VERTEXATTRIB,         /* u32 idx,size,type,norm,stride,offset        */
    PADGL_ENABLEATTRIB,         /* u32 idx                                     */
    PADGL_DISABLEATTRIB,        /* u32 idx                                     */

    PADGL_CREATESHADER,         /* u32 name,type                               */
    PADGL_SHADERSOURCE,         /* u32 name,len + source text                  */
    PADGL_COMPILESHADER,        /* u32 name                                    */
    PADGL_CREATEPROGRAM,        /* u32 name                                    */
    PADGL_ATTACHSHADER,         /* u32 prog,shader                             */
    PADGL_BINDATTRIBLOC,        /* u32 prog,idx + name text                    */
    PADGL_LINKPROGRAM,          /* u32 prog                                    */
    PADGL_USEPROGRAM,           /* u32 prog                                    */
    PADGL_UNIFORM,              /* u32 prog,slot,kind,count + floats/ints      */
    PADGL_REGUNIFORM,           /* u32 prog,slot + name text                   */

    PADGL_GENFBO,               /* u32 name                                    */
    PADGL_BINDFBO,              /* u32 target,name                             */
    PADGL_FBOTEX,               /* u32 target,att,textarget,tex,level          */

    PADGL_DRAWARRAYS,           /* u32 mode,first,count                        */
    PADGL_DRAWELEMENTS,         /* u32 mode,count,type,offset                  */
    PADGL_REGATTRIB,            /* u32 prog,slot + name text                   */

    /* VIDEO. The game never uploads a video frame with glTexImage2D: it uses
     * the Vivante GL_VIV_direct_texture extension, resolved through
     * eglGetProcAddress, to hand the driver a YUV pointer and let the texture
     * unit convert. There is no such extension on the host, so the host does
     * the conversion in software and uploads RGBA.
     *
     * u32 w, h, fmt, src, arg, len.  src says where the pixels are:
     *   PADGL_SRC_INLINE - `len` bytes follow this header
     *   PADGL_SRC_VIDSHM - `arg` is a byte offset into the video ring the host
     *                      already has open, and nothing follows. That is the
     *                      normal case and it keeps 1.5 MB per frame out of
     *                      both the emulated guest and this ring.            */
    PADGL_TEXDIRECT,
    PADGL_OP_MAX
};

/* Where a PADGL_TEXDIRECT payload lives. */
enum { PADGL_SRC_INLINE = 0, PADGL_SRC_VIDSHM };

/* Vivante direct-texture formats. Only I420 is ever seen from this game. */
#define PADGL_VIV_YV12 0x8FC0u
#define PADGL_VIV_NV12 0x8FC1u
#define PADGL_VIV_YUY2 0x8FC2u
#define PADGL_VIV_UYVY 0x8FC3u
#define PADGL_VIV_NV21 0x8FC4u
#define PADGL_VIV_I420 0x8FC5u

/* Attribute "locations" handed back to the game are tokens, not real indices:
 * the guest cannot know what the host's linker assigned. Anything at or above
 * this base is (prog,slot) to be resolved by name on the host; anything below
 * is a literal index the shader fixed with a layout qualifier. */
#define PADGL_ATTR_TOKEN_BASE 0x4000
#define PADGL_ATTR_PER_PROG   8

/* Uniform kinds for PADGL_UNIFORM */
enum { PADGL_U1F = 0, PADGL_U2F, PADGL_U3F, PADGL_U4F, PADGL_U1I, PADGL_U4FV, PADGL_UM4FV };

#endif
