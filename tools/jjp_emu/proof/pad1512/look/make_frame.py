"""The PAD-1512 look proof's menu frame: a purple panel with a gold rim and candy stripes."""
import sys
from PIL import Image, ImageDraw

out = sys.argv[1]
W, H = 520, 584
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
for y in range(H):                      # purple, darker toward the bottom
    t = y / H
    d.line([(0, y), (W, y)], fill=(int(70 - 40 * t), int(10 + 5 * t), int(110 - 50 * t), 235))
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=40, fill=255)
img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (W, H), 0), mask))
d = ImageDraw.Draw(img)
d.rounded_rectangle([3, 3, W - 4, H - 4], radius=38, outline=(255, 210, 60, 255), width=7)
d.rounded_rectangle([16, 16, W - 17, H - 17], radius=30, outline=(255, 120, 200, 200), width=2)
for i in range(-H, W, 36):              # candy stripes along the top and bottom
    for y0 in (26, H - 54):
        d.polygon([(i, y0 + 28), (i + 18, y0 + 28), (i + 46, y0), (i + 28, y0)], fill=(255, 255, 255, 60))
img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (W, H), 0), mask))
img.save(out)
print("wrote", out, img.size)
