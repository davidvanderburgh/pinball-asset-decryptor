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
/* 2: PADGL_TARGET (item 44). The host writes the version and the guest
 * refuses a mismatch at attach (glbridge.c), and padgl.h is on BOTH source
 * lists, so bumping it here makes both halves stale together - a new-host/
 * old-guest pair fails loudly instead of dropping ops on the floor. */
#define PADGL_VERSION 3          /* 3: PADGL_PRESENTTEX (PAD-1090, Spike 3) */

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
    /* ★ ITEM 43 HAD TWO FLAG FIELDS HERE (menu_flag, mode_flag) carrying a
     * "the game is in its service menu" signal from the renderer and from a
     * host-side memory poller to the video shim. The item was fixed in
     * glbridge.c instead - the menu's band was the Vivante direct-texture
     * registration being one process-global for a per-texture API - so both
     * signals and both their producers are gone. Removing them is safe in the
     * way appending them was: the ring data starts at the fixed
     * PADGL_HDR_BYTES page boundary, so no other field moves. */
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

    /* ★ ITEM 44: WHICH DISPLAY THE OPS THAT FOLLOW BELONG TO. A two-display
     * title (star_wars's playfield LCD, Stranger Things' projector) renders
     * its scenes ALTERNATELY - one scene, one swap, the other scene, the
     * other swap, measured as item 27's perfect 2x60/4x60 interleave - so a
     * single "current target" marker is exact: every op between two TARGETs
     * belongs to one scene. The guest emits it from eglMakeCurrent when the
     * game switches draw surfaces (the only way to switch scenes in EGL),
     * and the host routes guest-FBO-0 rendering and the following SWAP to
     * that display's own texture, framebuffer and window.
     *
     * u32 display index (0 = backbox LCD, the primary; star_wars and
     * stranger_things both use 2 for the second display). */
    PADGL_TARGET,
    /* ★ APPENDED 2026-09-01 (king_kong_le, David's E2E sweep): the game's
     * image sequences - the theatre CURTAIN that opens on the intro film -
     * patch their BC3 atlases frame by frame with glCompressedTexSubImage2D,
     * and the guest half of this bridge answered that call with a stub that
     * returned 0 and emitted nothing. The atlas stayed on the frame it was
     * created with, so the curtain never moved while the film played behind
     * it for the whole 30 s intro. Appended, not inserted, so every op above
     * keeps its number. */
    PADGL_TEXCOMPRESSEDSUB,     /* u32 lvl,x,y,w,h,fmt,size + data             */
    /* PAD-1090, SPIKE 3: THE FRAME IS A TEXTURE, NOT FBO 0. A Spike 3 game
     * (Godot 4 under Stern's KMS display server) never swaps a window
     * surface: it renders into a GBM buffer bound to a texture through
     * glEGLImageTargetTexture2DOES and page-flips that buffer. The guest
     * (tools/spike3_emu/s3gl.c) sends this at the flip; the host blits the
     * texture into the screen framebuffer and then does exactly what SWAP
     * does (present, frame_ack). Appended, so every op above keeps its
     * number; Spike 2 never sends it.
     *
     * u32 guest texture name, width, height */
    PADGL_PRESENTTEX,
    /* PAD-1090, SPIKE 3: THE REST OF GLES 3 THAT GODOT 4 USES. Until these
     * the Spike 3 guest answered each with a stub that did nothing, so an
     * instanced batch, a uniform block, a uniform array past its first
     * element and a colour mask were all silently lost (the game's video
     * pass draws into the frame and the UI that should let it through
     * covered it black). Appended, so every op above keeps its number;
     * Spike 2 never sends them. Attribute indices are the usual tokens
     * (attr_resolve), buffers/programs guest names (map_buf / map_obj). */
    PADGL_DRAWARRAYSINST,       /* u32 mode,first,count,instances              */
    PADGL_DRAWELEMSINST,        /* u32 mode,count,type,offset,instances        */
    PADGL_ATTRIBDIVISOR,        /* u32 idx,divisor                             */
    PADGL_VERTEXATTRIBI,        /* u32 idx,size,type,stride,offset (integer)   */
    PADGL_VERTEXATTRIBC,        /* u32 idx,kind (0 = 4f, 1 = I4ui) + 4 words   */
    PADGL_UBOBINDING,           /* u32 prog,binding + block name text          */
    PADGL_BINDBUFBASE,          /* u32 target,index,buffer                     */
    PADGL_BINDBUFRANGE,         /* u32 target,index,buffer,offset,size         */
    PADGL_UNIFORMN,             /* u32 prog,slot,kind,count + data (PADGL_UN_*)*/
    PADGL_COLORMASK,            /* u32 r,g,b,a                                 */
    PADGL_DEPTHMASK,            /* u32 flag                                    */
    PADGL_PIXELSTORE,           /* u32 pname,param                             */
    PADGL_STATE1,               /* u32 which (PADGL_S1_*), value               */
    PADGL_BLENDCOLOR,           /* f32 r,g,b,a                                 */
    PADGL_TEXIMAGE3D,           /* u32 target,lvl,ifmt,w,h,d,fmt,type + pixels */
    PADGL_TEXSUBIMAGE3D,        /* u32 target,lvl,x,y,z,w,h,d,fmt,type + pixels*/
    PADGL_GENMIPMAP,            /* u32 target                                  */
    PADGL_TEXSTORAGE2D,         /* u32 target,levels,ifmt,w,h                  */
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

/* Uniform kinds for PADGL_UNIFORMN (Spike 3): each is the GL call of that
 * name with `count` elements of data following. */
enum { PADGL_UN_1FV = 0, PADGL_UN_2FV, PADGL_UN_3FV, PADGL_UN_4FV,
       PADGL_UN_1IV, PADGL_UN_2IV, PADGL_UN_3IV, PADGL_UN_4IV,
       PADGL_UN_1UIV, PADGL_UN_2UIV, PADGL_UN_3UIV, PADGL_UN_4UIV,
       PADGL_UN_M2FV, PADGL_UN_M3FV, PADGL_UN_M4FV };

/* PADGL_STATE1 (Spike 3): one-value state calls */
enum { PADGL_S1_CULLFACE = 0, PADGL_S1_FRONTFACE, PADGL_S1_DEPTHFUNC,
       PADGL_S1_CLEARDEPTH /* value is an f32's bits */ };

#endif
