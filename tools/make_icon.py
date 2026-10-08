"""Draw the app logo and save it as assets/icon.ico and ui/logo.png."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1024
BACKGROUND_TOP, BACKGROUND_BOTTOM = (34, 58, 55), (17, 28, 27)
BAR, DOT = (63, 208, 184), (239, 106, 82)

# Vertical gradient clipped to a rounded square.
gradient = Image.new("RGB", (SIZE, SIZE))
draw = ImageDraw.Draw(gradient)
for y in range(SIZE):
    t = y / (SIZE - 1)
    draw.line([(0, y), (SIZE, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM)))
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=230, fill=255)
logo = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
logo.paste(gradient, (0, 0), mask)

# A sound wave of five rounded bars, with a record dot above it.
draw = ImageDraw.Draw(logo)
heights = [0.22, 0.44, 0.62, 0.38, 0.20]
width, gap = 92, 62
left = (SIZE - (len(heights) * width + (len(heights) - 1) * gap)) / 2
middle = SIZE * 0.56
for i, height in enumerate(heights):
    x = left + i * (width + gap)
    half = SIZE * height / 2
    draw.rounded_rectangle([x, middle - half, x + width, middle + half], radius=width / 2, fill=BAR)
draw.ellipse([SIZE - 330, 150, SIZE - 190, 290], fill=DOT)

(ROOT / "assets").mkdir(exist_ok=True)
logo.resize((256, 256), Image.LANCZOS).save(
    ROOT / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
logo.resize((96, 96), Image.LANCZOS).save(ROOT / "ui" / "logo.png")
logo.resize((256, 256), Image.LANCZOS).save(ROOT / "assets" / "icon.png")
print("icon written")
