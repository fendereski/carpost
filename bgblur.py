#!/usr/bin/env python3
"""
Soften the background of car photos so dealer signs / other cars are unreadable, keeping the car sharp.

usage:
  python3 bgblur.py in/car/01.jpg --out in/car/soft/01.jpg            # auto mask (car sharp, rest blurred)
  python3 bgblur.py in/car/06.jpg --out ... --rect 550,90,930,290       # blur only a rectangle (e.g. a window)
  python3 bgblur.py in/car/*.jpg --outdir in/car/soft --auto           # batch
options: --radius 16 (blur strength), --dim 0.85 (darken bg), --desat 0.8
"""
import argparse, os, sys, pathlib
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw

def mask_for(im):
    """Car mask = agreement of two segmentation models (isnet + u2net), so stray objects that only
    one model attaches to the car (a canopy, a neighbouring car) fall back into the blurred background.
    Pure onnxruntime implementation, see seg.py."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import seg
    return seg.car_mask(im, grow=2)


def soften(im, mask, radius=16, dim=0.85, desat=0.8):
    bg = im.filter(ImageFilter.GaussianBlur(radius))
    bg = ImageEnhance.Color(bg).enhance(desat)
    bg = ImageEnhance.Brightness(bg).enhance(dim)
    # soft edge so the car doesn't look pasted
    soft = mask.filter(ImageFilter.GaussianBlur(2))
    return Image.composite(im, bg, soft)


def extend_canvas(im, W=1080, H=1350, y_frac=0.5, strip_frac=0.08, blur=45, feather=28, fill="extend"):
    """Fit `im` to a WxH canvas. The photo is scaled to full width; the missing height is filled either by
    fill="extend": stretching + blurring the photo's own top strip (sky) upwards and bottom strip (ground)
                   downwards, so an exterior shot looks continuous instead of letterboxed;
    fill="black":  plain black bands (used for interior / engine / odometer strips).
    y_frac = where the photo sits vertically (0.5 = centred)."""
    scale = W / im.width
    h = round(im.height * scale)
    im2 = im.resize((W, h), Image.LANCZOS)
    if h >= H:                                   # already tall enough -> centre crop
        top = (h - H) // 2
        return im2.crop((0, top, W, top + H))
    free = H - h
    top = int(free * y_frac)
    bottom = H - h - top
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    if fill == "black":
        canvas.paste(im2, (0, top))
        return canvas
    s = max(6, int(h * strip_frac))
    if top > 0:
        band = im2.crop((0, 0, W, s)).resize((W, top + feather), Image.BILINEAR).filter(ImageFilter.GaussianBlur(blur))
        canvas.paste(band, (0, 0))
    if bottom > 0:
        band = im2.crop((0, h - s, W, h)).resize((W, bottom + feather), Image.BILINEAR).filter(ImageFilter.GaussianBlur(blur))
        canvas.paste(band, (0, top + h - feather))
    # feathered paste of the photo so the seams disappear
    mask = Image.new("L", (W, h), 255)
    d = ImageDraw.Draw(mask)
    for i in range(feather):
        v = int(255 * i / feather)
        if top > 0:
            d.line([(0, i), (W, i)], fill=v)
        if bottom > 0:
            d.line([(0, h - 1 - i), (W, h - 1 - i)], fill=v)
    canvas.paste(im2, (0, top), mask)
    return canvas


def blur_rects(im, rects, radius=18):
    out = im.copy()
    for (x1, y1, x2, y2) in rects:
        region = im.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(radius))
        # feathered paste
        m = Image.new("L", region.size, 0)
        ImageDraw.Draw(m).rectangle((6, 6, region.width - 6, region.height - 6), fill=255)
        m = m.filter(ImageFilter.GaussianBlur(6))
        out.paste(region, (x1, y1), m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--outdir")
    ap.add_argument("--auto", action="store_true", help="mask-based background blur")
    ap.add_argument("--rect", action="append", default=[], help="x1,y1,x2,y2 region to blur (repeatable)")
    ap.add_argument("--radius", type=float, default=16)
    ap.add_argument("--dim", type=float, default=0.85)
    ap.add_argument("--desat", type=float, default=0.8)
    a = ap.parse_args()
    rects = [tuple(int(v) for v in r.split(",")) for r in a.rect]
    from PIL import ImageOps
    for p in a.photos:
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        if a.auto or not rects:
            im = soften(im, mask_for(im), a.radius, a.dim, a.desat)
        if rects:
            im = blur_rects(im, rects, a.radius)
        if a.out and len(a.photos) == 1:
            dst = a.out
        else:
            dst = os.path.join(a.outdir or os.path.join(os.path.dirname(p), "soft"), os.path.basename(p))
        pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, quality=95)
        print("wrote", dst)


if __name__ == "__main__":
    main()
