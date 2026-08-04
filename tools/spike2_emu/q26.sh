#!/bin/bash
# Q26: exact EGL/GLES import surface, so the rasterizer covers all of it and
# nothing silently stays a no-op.
G=/home/david/spike2root/games/godzilla_pro/game
echo "### undefined EGL/GL symbols the game imports ###"
arm-linux-gnueabihf-objdump -T $G | awk '$4=="*UND*" || $2=="DF" {print $NF}' \
  | grep -E '^(egl|gl|fb)' | sort -u > /tmp/glsyms.txt
wc -l < /tmp/glsyms.txt
echo
echo "--- buffers / VAO / attribute plumbing (decides how vertices reach us) ---"
grep -E 'Buffer|Vertex|Attrib|Array' /tmp/glsyms.txt
echo
echo "--- uniforms / program ---"
grep -E 'Uniform|Program|Shader' /tmp/glsyms.txt
echo
echo "--- texture ---"
grep -E 'Tex|Pixel' /tmp/glsyms.txt
echo
echo "--- blend / raster state ---"
grep -E 'Blend|Enable|Disable|Viewport|Scissor|Clear|Depth|Cull' /tmp/glsyms.txt
echo
echo "--- everything else ---"
grep -vE 'Buffer|Vertex|Attrib|Array|Uniform|Program|Shader|Tex|Pixel|Blend|Enable|Disable|Viewport|Scissor|Clear|Depth|Cull' /tmp/glsyms.txt
