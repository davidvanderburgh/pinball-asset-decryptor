// PAD-448 (DragonRR): a Video tab player drawn through its colour steps the way Scenes
// draws a picture.  The SVG filter (video.js LookFilter) has no form for a profile's
// colour ranges, so a profile made of them did nothing to a clip, and the rest came
// close rather than the same.  Python works each player's steps out as a colour table
// (core/colour_profile.py build_look_lut: every 5th level through the picture maths) and
// this draws the <video>, frame by frame as it plays, or its still, through that table on
// the GPU, on a canvas laid over the player.  Where WebGL 2 is missing, or until the table
// is here, the SVG filter stands in (onLive tells the player which).

import { html, useEffect, useRef, mediaUrl } from "../core/ui.js";

const VERT = `#version 300 es
in vec2 p;
out vec2 uv;
void main() { uv = vec2((p.x + 1.0) * 0.5, (1.0 - p.y) * 0.5); gl_Position = vec4(p, 0.0, 1.0); }`;
// the table's points sit on texel centres: 0 and 255 land on the first and last
const FRAG = `#version 300 es
precision highp float;
precision highp sampler3D;
uniform sampler2D src;
uniform sampler3D lut;
uniform float n;
in vec2 uv;
out vec4 o;
void main() {
  vec3 c = texture(src, uv).rgb;
  o = vec4(texture(lut, c * ((n - 1.0) / n) + 0.5 / n).rgb, 1.0);
}`;

// path -> Promise of the table's bytes, shared by every player
const tables = new Map();
function table(path) {
  let p = tables.get(path);
  if (!p) {
    p = fetch(mediaUrl(path)).then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(String(r.status)))))
      .then((b) => new Uint8Array(b));
    p.catch(() => tables.delete(path));
    if (tables.size > 24) tables.delete(tables.keys().next().value);
    tables.set(path, p);
  }
  return p;
}

function setup(canvas) {
  const gl = canvas.getContext("webgl2", { alpha: false, antialias: false, premultipliedAlpha: false });
  if (!gl) return null;
  const sh = (type, text) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, text);
    gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  };
  const vs = sh(gl.VERTEX_SHADER, VERT), fs = sh(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return null;
  const prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "p");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  for (const [unit, target] of [[0, gl.TEXTURE_2D], [1, gl.TEXTURE_3D]]) {
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(target, gl.createTexture());
    gl.texParameteri(target, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(target, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(target, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(target, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    if (target === gl.TEXTURE_3D) gl.texParameteri(target, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
  }
  gl.uniform1i(gl.getUniformLocation(prog, "src"), 0);
  gl.uniform1i(gl.getUniformLocation(prog, "lut"), 1);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  return { gl, n: gl.getUniformLocation(prog, "n") };
}

// media: a ref to the player's <video> (empty while it has none) and mediaKey, which changes
// with that element; poster: its still's path; lut: the table's path (null: draw nothing);
// onLive(on): whether the canvas is showing the player (then its own SVG filter is dropped).
export function LookGL({ media, mediaKey, poster, lut, onLive }) {
  const ref = useRef(null);
  const st = useRef(null);
  if (!st.current) st.current = { ctx: null, lut: null, img: null, frames: false, live: false, raf: 0, vfc: 0 };
  const live = (on) => {
    const s = st.current;
    if (s.live === on) return;
    s.live = on;
    if (ref.current) ref.current.style.visibility = on ? "visible" : "hidden";
    onLive(on);
  };

  function draw() {
    const s = st.current;
    const c = ref.current;
    if (!s.ctx || !s.lut || !c) return live(false);
    const v = media && media.current;
    let src = null;
    if (v && (s.frames || !s.img)) {
      // between frames (a seek on its way): what is drawn stays
      if (v.readyState < 2 || !v.videoWidth) return undefined;
      src = v;
    } else if (s.img && s.img.complete && s.img.naturalWidth) {
      src = s.img;
    }
    if (!src) return live(false);
    const w = src.videoWidth || src.naturalWidth, h = src.videoHeight || src.naturalHeight;
    const { gl } = s.ctx;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    gl.viewport(0, 0, w, h);
    gl.activeTexture(gl.TEXTURE0);
    try {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, src);
    } catch (e) {
      return live(false);
    }
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return live(true);
  }

  // the context, once per canvas, given back when the player goes (a page may hold only
  // so many)
  useEffect(() => {
    const s = st.current;
    const c = ref.current;
    s.ctx = c ? setup(c) : null;
    if (!s.ctx) return undefined;
    const lost = (e) => { e.preventDefault(); s.ctx = null; live(false); };
    c.addEventListener("webglcontextlost", lost);
    return () => {
      c.removeEventListener("webglcontextlost", lost);
      const ext = s.ctx && s.ctx.gl.getExtension("WEBGL_lose_context");
      s.ctx = null;
      if (ext) ext.loseContext();
      onLive(false);
    };
  }, []);

  // the table: the last one stays until the next is here, so a slider never flashes
  useEffect(() => {
    const s = st.current;
    if (!lut || !s.ctx) { s.lut = null; draw(); return undefined; }
    let gone = false;
    table(lut).then((bytes) => {
      if (gone || !s.ctx) return;
      const n = Math.round(Math.cbrt(bytes.length / 3));
      if (n < 2 || n * n * n * 3 !== bytes.length) return;
      const { gl } = s.ctx;
      gl.activeTexture(gl.TEXTURE1);
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGB8, n, n, n, 0, gl.RGB, gl.UNSIGNED_BYTE, bytes);
      gl.uniform1f(s.ctx.n, n);
      s.lut = lut;
      draw();
    }, () => {});
    return () => { gone = true; };
  }, [lut]);

  // the still, until the clip plays or seeks (as a <video> shows its poster)
  useEffect(() => {
    const s = st.current;
    s.img = null;
    if (!poster) { draw(); return undefined; }
    const img = new Image();
    img.onload = () => { if (s.img === img) draw(); };
    img.src = mediaUrl(poster);
    s.img = img;
    draw();
    return () => { img.onload = null; };
  }, [poster]);

  // the clip's frames: each new one while it plays, and the one a seek lands on
  useEffect(() => {
    const s = st.current;
    s.frames = false;
    const v = media && media.current;
    if (!v) { draw(); return undefined; }
    const schedule = () => {
      if (v.paused || v.ended || s.vfc || s.raf) return;
      if (v.requestVideoFrameCallback) s.vfc = v.requestVideoFrameCallback(tick) || -1;
      else s.raf = requestAnimationFrame(tick);
    };
    function tick() { s.vfc = 0; s.raf = 0; draw(); schedule(); }
    const go = () => { s.frames = true; draw(); schedule(); };
    const once = () => draw();
    // load() puts the poster back up
    const reset = () => { s.frames = false; };
    const on = [["play", go], ["seeking", go], ["seeked", once], ["loadeddata", once],
                ["pause", once], ["emptied", reset]];
    for (const [ev, fn] of on) v.addEventListener(ev, fn);
    if (!v.paused) go(); else draw();
    return () => {
      for (const [ev, fn] of on) v.removeEventListener(ev, fn);
      if (s.vfc > 0 && v.cancelVideoFrameCallback) v.cancelVideoFrameCallback(s.vfc);
      if (s.raf) cancelAnimationFrame(s.raf);
      s.vfc = 0; s.raf = 0;
    };
  }, [mediaKey]);

  return html`<canvas ref=${ref} class="vid-gl" style="visibility:hidden" aria-hidden="true"></canvas>`;
}
