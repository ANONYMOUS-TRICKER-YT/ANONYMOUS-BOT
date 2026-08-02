from PIL import Image, ImageDraw, ImageFont

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

GOLD = (245, 197, 66)
WHITE = (255, 255, 255)
GRAY = (205, 212, 224)

ITEMS = {
    "1": ("REPLIT", "1 Month Access"),
    "2": ("CANVA + LEONARDO AI", "8500 Points  -  1 Month Account"),
    "3": ("CANVA + LEONARDO AI", "Per Seat Invite"),
    "4": ("CANVA BUSINESS", "1 Month Trial Account"),
    "5": ("GEMINI PRO", "18 Months  -  5TB Storage"),
}


def font(path, size):
    return ImageFont.truetype(path, size)


def text_w(draw, s, f):
    b = draw.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def wrap(draw, s, f, max_w):
    words = s.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if text_w(draw, test, f) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_title(draw, s, max_w, max_h, start):
    """Shrink the title font until both width (wrapped) and total height fit."""
    size = start
    while size > 28:
        f = font(BOLD, size)
        lines = wrap(draw, s, f, max_w)
        line_h = int(size * 1.12)
        if all(text_w(draw, ln, f) <= max_w for ln in lines) and line_h * len(lines) <= max_h:
            return f, lines, line_h
        size -= 2
    f = font(BOLD, size)
    return f, wrap(draw, s, f, max_w), int(size * 1.12)


def left_scrim(img):
    """Dark gradient on the left half so overlaid text is always readable."""
    W, H = img.size
    grad = Image.new("L", (W, 1), 0)
    px = grad.load()
    edge = int(W * 0.60)
    for x in range(W):
        if x < edge:
            a = int(200 * (1 - x / edge))
        else:
            a = 0
        px[x, 0] = a
    grad = grad.resize((W, H))
    black = Image.new("RGB", (W, H), (3, 6, 14))
    img.paste(black, (0, 0), grad)
    return img


for pid, (title, sub) in ITEMS.items():
    src = f"product_images/raw/{pid}.png"
    img = Image.open(src).convert("RGB")
    W, H = img.size
    img = left_scrim(img)
    d = ImageDraw.Draw(img)

    margin = int(W * 0.055)
    area_w = int(W * 0.52) - margin
    x = margin
    y = int(H * 0.16)

    # Brand
    bf = font(BOLD, int(H * 0.052))
    d.text((x, y), "CHEAP AI TOOLS", font=bf, fill=GOLD)
    y += int(H * 0.052) + int(H * 0.012)
    tf = font(BOLD, int(H * 0.032))
    d.text((x, y), "TRUSTED  -  FAST  -  BEST PRICE", font=tf, fill=GOLD)
    y += int(H * 0.030) + int(H * 0.09)

    # Title (auto-fit + wrap)
    tfont, lines, lh = fit_title(d, title, area_w, int(H * 0.34), int(H * 0.135))
    for ln in lines:
        d.text((x, y), ln, font=tfont, fill=WHITE)
        y += lh
    y += int(H * 0.02)

    # Gold accent underline
    d.rectangle([x, y, x + int(area_w * 0.5), y + max(3, int(H * 0.007))], fill=GOLD)
    y += int(H * 0.045)

    # Subtitle
    sf = font(BOLD, int(H * 0.044))
    for ln in wrap(d, sub, sf, area_w):
        d.text((x, y), ln, font=sf, fill=GRAY)
        y += int(H * 0.044) + 6

    img.save(f"product_images/{pid}.png", "PNG")
    print("done", pid, "->", title, "|", sub)

print("ALL DONE")
