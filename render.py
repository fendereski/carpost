#!/usr/bin/env python3
"""
Render Instagram carousel slides (1080x1350, Persian RTL) for one car.

usage: python3 render.py car.json [--brand brand.json] [--out out/<slug>]

car.json — written by Claude from the owner's specs text (see RULES.md / RUN.md):
  title        Persian title, e.g. "تویوتا کرولا الیت"          (required)
  model_en     Latin line, e.g. "Toyota Corolla Elite"
  year         "2023"
  engine / hp / gearbox / fuel / color   -> badges on the cover (only what the owner stated)
  mileage_km | mileage_mi                -> badge, always shown in km
  options      ["سانروف", "AWD", ...]     -> chips on the cover (max 3 shown)
  price        "11,000 دلار"             -> price box on the cover (omit if the owner gave no price)
  terms        "پیش‌پرداخت 4,000 دلار | مابقی 7,000 دلار هنگام ترخیص"
  tag          short pill next to the code, e.g. "هیبرید | چهارچرخ محرک"
  code         "004" (set by job.py from the queue)
  cover        path of the cover photo (default photos[0]); must be one of photos
  photos       [{"file": "...", "label": "نمای عقب", "soften": true}, ...]
                 soften: true  -> EXTERIOR: car mask -> background softened -> crop around the car -> fill 4:5
                                  by extending the photo's own sky/ground (no bars).
                 (no soften)   -> INTERIOR: fills the frame; a panoramic strip (w/h > 1.5) is side-cropped
                                  around the subject and padded with plain black.
                 keep_x: [from, to] fractions -> manual side-crop range for a panoramic interior.
                 blur_rects: [[x1,y1,x2,y2]] pixels -> blur a readable shop sign seen through a window.
  contact      true/false (default true) -> last slide with phones / IG / site + "comment the code"

brand.json: name, name_sub, logo (white PNG, shown top-right on EVERY slide), accent, accent_fg, tag, handle,
            website, phones[] (strings, or {"number", "label"} e.g. label "واتساپ"), instagram, telegram,
            address, lead, foot_right, persian_digits
"""
import json, os, re, sys, argparse, pathlib, html
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
TPL = HERE / "templates"
sys.path.insert(0, str(TPL))
from icons import ICONS  # noqa

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(s, on=True):
    return s.translate(FA_DIGITS) if (on and isinstance(s, str)) else s


def esc(s):
    return html.escape(str(s), quote=True)


def file_url(p):
    return pathlib.Path(p).resolve().as_uri()


def fill(template, mapping):
    out = template
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", "" if v is None else str(v))
    # drop any leftover placeholders
    return re.sub(r"\{\{[a-zA-Z_]+\}\}", "", out)


def write_css(brand):
    css = (TPL / "base.css").read_text(encoding="utf-8")
    css = fill(css, {
        "accent": brand.get("accent", "#e0b454"),
        "accent_fg": brand.get("accent_fg", "#111111"),
        "fit": "cover", "focus": "center",
    })
    (TPL / "_base.css").write_text(css, encoding="utf-8")


def brand_html(brand, size="full"):
    """Top-right brand block. With a logo file (it already carries the wordmark) only the logo + sub-line
    are shown; without a logo the name is set in type."""
    logo = brand.get("logo")
    name = brand.get("name", "")
    sub = brand.get("name_sub", "")
    has_logo = bool(logo and os.path.exists(logo))
    parts = ['<div class="brand stack">' if has_logo else '<div class="brand">']
    if has_logo:
        parts.append(f'<img src="{file_url(logo)}" alt="">')
        if sub:
            parts.append(f'<div class="sub under">{esc(sub)}</div>')
    elif name:
        parts.append(f'<div><div class="name">{esc(name)}</div>' + (f'<div class="sub">{esc(sub)}</div>' if sub else "") + "</div>")
    parts.append("</div>")
    return "".join(parts)


def mini_brand_html(brand):
    logo = brand.get("logo")
    if logo and os.path.exists(logo):
        return f'<img src="{file_url(logo)}" alt="">'
    return f'<span>{esc(brand.get("name", ""))}</span>'


def has_latin(s):
    return bool(re.search(r"[A-Za-z]", str(s)))


LATIN_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-/]*(?:\s+[A-Za-z0-9][A-Za-z0-9.\-/]*)*")


def rich(s, pd=True):
    """Escape text; keep Latin runs (letters, model codes like 'RX 350h', 'AWD') LTR with Latin digits,
    convert digits in the Persian parts to Persian digits when pd is on."""
    s = str(s)
    out, pos = [], 0
    for m in LATIN_RUN.finditer(s):
        seg = m.group(0)
        if not has_latin(seg):          # pure number inside Persian text -> treat as Persian
            continue
        out.append(esc(fa(s[pos:m.start()], pd)))
        out.append(f'<span class="latin">{esc(seg)}</span>')
        pos = m.end()
    out.append(esc(fa(s[pos:], pd)))
    return "".join(out)


REGISTRY = HERE / "registry.json"
MI_TO_KM = 1.609344


def load_registry():
    if REGISTRY.exists():
        return json.load(open(REGISTRY, encoding="utf-8"))
    return {"next": 1, "cars": []}


def assign_code(car, car_path):
    """Give the car a sequential 3-digit code (001, 002, ...) and remember it in registry.json."""
    reg = load_registry()
    if car.get("code"):
        code = str(car["code"]).zfill(3)
    else:
        code = f"{reg['next']:03d}"
        car["code"] = code
        reg["next"] += 1
        json.dump(car, open(car_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if not any(c.get("code") == code for c in reg["cars"]):
        import datetime
        reg["cars"].append({"code": code, "slug": car.get("slug"), "title": car.get("title"),
                            "date": datetime.date.today().isoformat()})
        reg["next"] = max(reg["next"], int(code) + 1)
        json.dump(reg, open(REGISTRY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return code


def fmt_int(n):
    return f"{int(round(n)):,}".replace(",", "٬")


def mileage_km_text(car):
    """Always express mileage in km. Accepts mileage_km / mileage_mi (numbers) or mileage (string)."""
    if car.get("mileage_km") is not None:
        km = float(car["mileage_km"])
    elif car.get("mileage_mi") is not None:
        km = float(car["mileage_mi"]) * MI_TO_KM
    elif car.get("mileage"):
        s = str(car["mileage"])
        m = re.search(r"[\d,\.]+", s)
        if not m:
            return s
        n = float(m.group(0).replace(",", ""))
        km = n * MI_TO_KM if re.search(r"mi|مایل", s, re.I) else n
    else:
        return None
    if km < 100:
        return "صفر"
    return f"{fmt_int(km)} کیلومتر"


def smart_crop_box(mask, size, target, mx=0.06, my=0.10):
    """Crop window (x0,y0,x1,y1) around the car bbox, pushed towards the target w/h ratio without cutting the car.
    mask: bool ndarray (True = car). Returns None if no car found."""
    import numpy as np
    W, H = size
    ys, xs = np.where(mask)
    if len(xs) < 50:
        return None
    x0, x1 = int(xs.min()), int(xs.max()); y0, y1 = int(ys.min()), int(ys.max())
    bw, bh = x1 - x0, y1 - y0
    # margins around the car
    cx0, cx1 = max(0, x0 - int(mx * bw)), min(W, x1 + int(mx * bw))
    cy0, cy1 = max(0, y0 - int(my * bh)), min(H, y1 + int(my * bh))
    cw, ch = cx1 - cx0, cy1 - cy0
    if cw / ch > target:                      # too wide -> grow height (sky/ground) as far as the image allows
        need = int(cw / target)
        extra = need - ch
        top = min(cy0, extra // 2); bottom = min(H - cy1, extra - top); top = min(cy0, extra - bottom)
        cy0 -= top; cy1 += bottom
    else:                                     # too narrow -> grow width symmetrically
        need = int(ch * target)
        extra = need - cw
        left = min(cx0, extra // 2); right = min(W - cx1, extra - left); left = min(cx0, extra - right)
        cx0 -= left; cx1 += right
        if (cx1 - cx0) / (cy1 - cy0) < target:  # image not wide enough -> trim height around the car instead
            need_h = int((cx1 - cx0) / target)
            if need_h >= bh:                  # only if the car still fits
                c = (y0 + y1) // 2
                ny0 = max(0, c - need_h // 2); ny1 = min(H, ny0 + need_h); ny0 = max(0, ny1 - need_h)
                if ny0 <= y0 and ny1 >= y1:
                    cy0, cy1 = ny0, ny1
    return (int(cx0), int(cy0), int(cx1), int(cy1))


def code_chip_html(code, pd=True):
    return f'<div class="code">کد <b>{fa(code, pd)}</b></div>' if code else ""


def badge(icon, val, lbl, pos, pd=True):
    cls = "val latin" if (has_latin(val) and not re.search(r"[؀-ۿ]", val)) else "val"
    return (f'<div class="badge" style="{pos}">'
            f'<div class="ico">{ICONS[icon]}</div>'
            f'<div><div class="{cls}">{rich(val, pd)}</div><div class="lbl">{esc(lbl)}</div></div></div>')


def price_block_html(car, pd=True):
    """Price + payment terms on the cover. `price` e.g. '10,000 دلار'; `terms` e.g. 'پیش‌پرداخت 3,000 دلار | مابقی 7,000 دلار هنگام ترخیص'."""
    price = (car.get("price") or "").strip()
    terms = (car.get("terms") or "").strip()
    if not price and not terms:
        return ""
    html_ = '<div class="pricebox">'
    if price:
        html_ += f'<div class="plabel">قیمت</div><div class="pval">{rich(price, pd)}</div>'
    if terms:
        html_ += f'<div class="pterms">{rich(terms, pd)}</div>'
    return html_ + "</div>"


def build_cover(car, brand):
    pd = brand.get("persian_digits", True)
    specs = []
    if car.get("engine"):  specs.append(("engine", car["engine"], "حجم موتور"))
    if car.get("hp"):      specs.append(("hp", car["hp"], "قدرت"))
    if car.get("gearbox"): specs.append(("gear", car["gearbox"], "گیربکس"))
    if car.get("fuel"):    specs.append(("fuel", car["fuel"], "سوخت"))
    km = mileage_km_text(car)
    if km:                 specs.append(("road", km, "کارکرد"))
    if car.get("color"):   specs.append(("color", car["color"], "رنگ"))
    specs = specs[:4]
    # positions: right column (first two), left column (next two)
    positions = ["top:250px; right:56px;", "top:400px; right:56px;",
                 "top:250px; left:56px;", "top:400px; left:56px;"]
    badges = "".join(badge(i, v, l, positions[n], pd) for n, (i, v, l) in enumerate(specs))

    opts = car.get("options") or []
    options_html = ""
    if opts:
        options_html = '<div class="options">' + "".join(
            f'<div class="opt">{ICONS["check"]}<span>{rich(o, pd)}</span></div>' for o in opts[:5]) + "</div>"

    tag = car.get("tag", brand.get("tag"))
    cover = car.get("cover") or car["photos"][0]
    cover = cover["file"] if isinstance(cover, dict) else cover

    tpl = (TPL / "cover.html").read_text(encoding="utf-8").replace("base.css", "_base.css")
    page = fill(tpl, {
        "photo": file_url(cover),
        "brand_html": brand_html(brand),
        "tag_html": '<div class="tagrow">' + code_chip_html(car.get("code"), pd) + (f'<div class="tag">{esc(tag)}</div>' if tag else "") + "</div>",
        "badges_html": badges,
        "title": rich(car["title"], pd),
        "year_html": f'<div class="year">{esc(car["year"])}</div>' if car.get("year") else "",
        "model_en_html": f'<div class="model-en latin">{esc(car["model_en"])}</div>' if car.get("model_en") else "",
        "options_html": options_html,
        "price_html": price_block_html(car, pd),
        "footer_right": esc(brand.get("foot_right", "")),
        "footer_left": esc(brand.get("handle", "")),
    })
    fit = car.get("cover_fit", "cover")
    focus = car.get("cover_focus", "center")
    extra = f".photo{{object-fit:{fit}; object-position:{focus};}}"
    # optional fine-tuning hooks
    if car.get("title_bottom"):
        extra += f".title-block{{bottom:{car['title_bottom']}px;}}"
    return page.replace("</style>", extra + "</style>")


def build_photo(item, idx, total, brand, code=None):
    if isinstance(item, str):
        item = {"file": item}
    fit = item.get("fit", "cover")
    focus = item.get("focus", "center")
    label = item.get("label")
    tpl = (TPL / "photo.html").read_text(encoding="utf-8").replace("base.css", "_base.css")
    page = fill(tpl, {
        "photo": file_url(item["file"]),
        "mini_brand_html": mini_brand_html(brand),
        "counter": f"{idx}/{total}",
        "code_html": code_chip_html(code, brand.get("persian_digits", True)),
        "label_html": f'<div class="label"><span class="dot"></span><span>{rich(label, brand.get("persian_digits", True))}</span></div>' if label else "",
        "handle": esc(brand.get("handle", "")),
    })
    # per-slide fit/focus override
    page = page.replace("</style>", f".photo{{object-fit:{fit}; object-position:{focus};}}</style>")
    return page


def build_contact(car, brand):
    pd = brand.get("persian_digits", True)
    rows = []
    for ph in brand.get("phones", []):
        # a phone is either "0912 000 0000" or {"number": "...", "label": "واتساپ"}
        number = ph["number"] if isinstance(ph, dict) else ph
        label = (ph.get("label") if isinstance(ph, dict) else None) or "تماس و واتساپ"
        rows.append(f'<div class="row"><div class="ico">{ICONS["phone"]}</div><div class="txt"><div class="big latin">{esc(number)}</div><div class="small">{esc(label)}</div></div></div>')
    if brand.get("instagram"):
        rows.append(f'<div class="row"><div class="ico">{ICONS["instagram"]}</div><div class="txt"><div class="big latin">@{esc(brand["instagram"])}</div><div class="small">اینستاگرام</div></div></div>')
    if brand.get("telegram"):
        rows.append(f'<div class="row"><div class="ico">{ICONS["telegram"]}</div><div class="txt"><div class="big latin">{esc(brand["telegram"])}</div><div class="small">تلگرام</div></div></div>')
    if brand.get("website"):
        rows.append(f'<div class="row"><div class="ico">{ICONS["globe"]}</div><div class="txt"><div class="big latin">{esc(brand["website"])}</div><div class="small">وب‌سایت</div></div></div>')
    if brand.get("address"):
        rows.append(f'<div class="row"><div class="ico">{ICONS["pin"]}</div><div class="txt"><div class="big" style="font-size:30px">{esc(fa(brand["address"], pd))}</div><div class="small">آدرس</div></div></div>')

    logo = brand.get("logo")
    if logo and os.path.exists(logo):
        logo_row = f'<img src="{file_url(logo)}" alt="">' + \
                   (f'<div class="sub under">{esc(brand.get("name_sub", ""))}</div>' if brand.get("name_sub") else "")
    else:
        logo_row = f'<div><div class="name">{esc(brand.get("name", ""))}</div>' + \
                   (f'<div class="sub">{esc(brand.get("name_sub", ""))}</div>' if brand.get("name_sub") else "") + "</div>"

    bg = car.get("contact_bg") or car.get("cover") or car["photos"][0]
    bg = bg["file"] if isinstance(bg, dict) else bg
    tpl = (TPL / "contact.html").read_text(encoding="utf-8").replace("base.css", "_base.css")
    return fill(tpl, {
        "bg_photo_html": f'<img class="photo-dim" src="{file_url(bg)}" alt="">' if bg else "",
        "logo_row_html": logo_row,
        "logo_row_class": " stack" if (logo and os.path.exists(logo)) else "",
        "headline": (f'برای دریافت مشخصات کامل، کد <em>{fa(car["code"], pd)}</em> را کامنت کنید'
                     if car.get("code") else brand.get("headline", "برای مشاوره و استعلام قیمت <em>همین حالا</em> تماس بگیرید")),
        "lead": esc(fa(brand.get("lead", ""), pd)) + ("<br>یا برای مشاوره و استعلام قیمت با شماره‌های زیر تماس بگیرید." if car.get("code") else ""),
        "rows_html": "".join(rows),
        "foot_right": esc(brand.get("foot_right", "")),
        "foot_left": esc(brand.get("handle", "")),
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("car")
    ap.add_argument("--brand", default=str(HERE / "brand.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--jpg", action="store_true", help="also write JPEG copies (quality 92)")
    a = ap.parse_args()

    car = json.load(open(a.car, encoding="utf-8"))
    brand = json.load(open(a.brand, encoding="utf-8")) if os.path.exists(a.brand) else {}
    code = assign_code(car, a.car)
    print("car code:", code, "| mileage:", mileage_km_text(car))

    # --- normalise every photo: EXIF rotation applied, RGB, long side <= 2400px ---
    from PIL import Image as _I, ImageOps as _IO
    try:
        import pillow_heif; pillow_heif.register_heif_opener()   # iPhone HEIC sent as a file
    except Exception:
        pass
    MAX_SIDE = 2400

    def normalised(item):
        d = dict(item) if isinstance(item, dict) else {"file": item}
        src = pathlib.Path(d["file"])
        dst = src.parent / "norm" / (src.stem + ".jpg")
        if not dst.exists():
            im = _IO.exif_transpose(_I.open(src)).convert("RGB")
            if max(im.size) > MAX_SIDE:
                im.thumbnail((MAX_SIDE, MAX_SIDE), _I.Resampling.LANCZOS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.save(dst, quality=95)
        d["file"] = str(dst)
        return d

    car["photos"] = [normalised(p) for p in car["photos"]]
    if car.get("cover"):
        cov = car["cover"]["file"] if isinstance(car["cover"], dict) else car["cover"]
        for p in car["photos"]:
            if pathlib.Path(p["file"]).stem == pathlib.Path(cov).stem:
                car["cover"] = p["file"]

    # --- exterior photos: car mask -> background softened + SMART CROP around the car ---
    # Body slides are cropped towards 4:5 (so no blurred bars); the cover is cropped towards 4:3
    # (the cover layout keeps the top band for badges and the bottom band for the title).
    SLIDE_RATIO, COVER_RATIO = 0.8, 1.3
    cover_src = car.get("cover")
    cover_src = cover_src["file"] if isinstance(cover_src, dict) else cover_src
    if not cover_src:
        cover_src = car["photos"][0]["file"]
    cover_src = str(cover_src)

    def exterior(item, for_cover=False):
        """Soften background + smart-crop. Returns (file, fit). Cached per (photo, cover/body)."""
        import bgblur, numpy as _np
        src = pathlib.Path(item["file"])
        tag = "_cover" if for_cover else ""
        dst = src.parent / "soft" / (src.stem + tag + ".jpg")
        meta = dst.with_suffix(".json")
        if dst.exists() and meta.exists():
            return str(dst), json.loads(meta.read_text())["fit"]
        im = _I.open(src).convert("RGB")
        mask = bgblur.mask_for(im)
        soft = bgblur.soften(im, mask, item.get("radius", 9), item.get("dim", 0.95), item.get("desat", 0.9))
        if item.get("blur_rects"):
            soft = bgblur.blur_rects(soft, [tuple(r) for r in item["blur_rects"]], item.get("radius", 9))
        box = smart_crop_box(_np.asarray(mask) > 127, im.size, COVER_RATIO if for_cover else SLIDE_RATIO)
        if box and not item.get("nocrop"):
            soft = soft.crop(box)
        # no letterbox bars: extend the photo's own sky/ground to fill the 1080x1350 canvas
        soft = bgblur.extend_canvas(soft, 1080, 1350, y_frac=(0.30 if for_cover else 0.5))
        fit = "cover"
        dst.parent.mkdir(parents=True, exist_ok=True)
        soft.save(dst, quality=95)
        meta.write_text(json.dumps({"fit": fit, "box": box, "size": list(soft.size)}))
        print(f"exterior {dst.name}: crop={box} -> {soft.size[0]}x{soft.size[1]}")
        return str(dst), fit

    def interior(item):
        """Interior / engine / odometer photos.
        - normal photos (w/h <= 1.5, e.g. 4:3 phone shots): fill the frame (cover), nothing else.
        - panoramic strips (w/h > 1.5): crop the SIDES only as far as the subject allows (subject = salient-object
          mask bbox + margin, never less than 70% of the width, or the author's keep_x=[from,to] fractions),
          then plain BLACK bands above/below (no blur) — like a manual crop in a photo editor.
        - keep_y=[from,to] fractions: author's vertical crop first (e.g. an odometer sitting at the bottom of a
          4:3 shot); if the remaining strip is panoramic the side-crop + black-band rule above applies to it.
        - optional blur_rects for a readable shop sign seen through a window."""
        import bgblur, numpy as _np, hashlib
        src = pathlib.Path(item["file"])
        im = _I.open(src).convert("RGB")
        w, h = im.size
        if item.get("keep_y"):
            y0, y1 = int(item["keep_y"][0] * h), int(item["keep_y"][1] * h)
            im = im.crop((0, y0, w, y1)); h = im.height
            print(f"interior {src.name}: keep y {y0}-{y1} -> {w}x{h}")
        wide = w / h > 1.5
        if not wide and not item.get("blur_rects") and not item.get("keep_y"):
            return item
        opts = json.dumps([item.get("keep_x"), item.get("keep_y"), item.get("blur_rects")])
        dst = src.parent / "soft" / (src.stem + "__i" + hashlib.md5(opts.encode()).hexdigest()[:6] + ".jpg")
        if not dst.exists():
            if item.get("blur_rects"):
                im = bgblur.blur_rects(im, [tuple(r) for r in item["blur_rects"]], item.get("radius", 14))
            if wide:
                if item.get("keep_x"):
                    x0, x1 = int(item["keep_x"][0] * w), int(item["keep_x"][1] * w)
                else:
                    m = _np.asarray(bgblur.mask_for(im)) > 127
                    if m.mean() > 0.02:
                        xs = _np.where(m.any(0))[0]
                        bx0, bx1 = int(xs.min()), int(xs.max())
                        pad = int(0.06 * (bx1 - bx0)); bx0 -= pad; bx1 += pad
                    else:
                        bx0, bx1 = w // 2, w // 2
                    keep = min(w, max(bx1 - bx0, int(0.70 * w), int(h * 0.8)))
                    c = (bx0 + bx1) // 2
                    x0 = max(0, min(w - keep, c - keep // 2)); x1 = x0 + keep
                im = im.crop((x0, 0, x1, h))
                print(f"interior {src.name}: keep x {x0}-{x1} of {w} -> {im.width}x{im.height}")
                if im.width / im.height > 0.84:   # still wider than 4:5 -> plain black bands, no blur
                    im = bgblur.extend_canvas(im, 1080, 1350, y_frac=0.5, fill="black")
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.save(dst, quality=95)
        new = dict(item); new["file"] = str(dst)
        return new

    new_photos = []
    for p in car["photos"]:
        if p.get("soften"):
            f, fit = exterior(p)
            q = dict(p); q["file"] = f
            q.setdefault("fit", fit)            # code decides unless the author forces a fit
            if fit == "contain":
                q.setdefault("focus", "center")
            new_photos.append(q)
        else:
            q = interior(p)
            q.setdefault("fit", "cover")        # interiors always fill the frame
            new_photos.append(q)
    car["photos"] = new_photos

    # cover: its own crop (4:3) of the same source photo
    base = lambda f: pathlib.Path(f).stem.replace("_cover", "").split("__p")[0]
    cover_item = next((p for p in car["photos"] if base(p["file"]) == base(cover_src)), None)
    src_item = next((p for p in [normalised(x) for x in json.load(open(a.car, encoding="utf-8"))["photos"]] if base(p["file"]) == base(cover_src)), None)
    if src_item and src_item.get("soften"):
        cf, cfit = exterior(src_item, for_cover=True)
        car["cover"] = cf
        car.setdefault("cover_fit", "cover")
        car.setdefault("cover_focus", "center")
    else:
        car["cover"] = cover_item["file"] if cover_item else (src_item["file"] if src_item else car["photos"][0]["file"])
        car.setdefault("cover_fit", "cover")
        car.setdefault("cover_focus", "center 40%")
    car.setdefault("title_bottom", 120)
    # the body slide of the cover photo is dropped below (same stem)
    cover_stem = base(cover_src)
    slug = car.get("slug") or re.sub(r"[^a-zA-Z0-9]+", "-", car.get("model_en", "car")).strip("-").lower() or "car"
    out = pathlib.Path(a.out or (HERE / "out" / slug))
    out.mkdir(parents=True, exist_ok=True)

    write_css(brand)
    photos = car["photos"]
    # photo slides = all photos except the one used for the cover (unless reuse_cover is true)
    body = [p for p in photos if base(p["file"]) != cover_stem] if not car.get("reuse_cover") else list(photos)
    want_contact = car.get("contact", True)
    total = 1 + len(body) + (1 if want_contact else 0)
    if total > 10:
        print(f"[warn] {total} slides > 10 (Instagram max). Trimming photos.")
        body = body[: 10 - 1 - (1 if want_contact else 0)]
        total = 1 + len(body) + (1 if want_contact else 0)

    pages = [("01-cover", build_cover(car, brand))]
    for i, item in enumerate(body, start=2):
        pages.append((f"{i:02d}-photo", build_photo(item, i, total, brand, code)))
    if want_contact:
        pages.append((f"{total:02d}-contact", build_contact(car, brand)))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for name, html_src in pages:
            tmp = TPL / f"_render_{name}.html"
            tmp.write_text(html_src, encoding="utf-8")
            page.goto(tmp.as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
            png = out / f"{name}.png"
            page.screenshot(path=str(png), full_page=False)
            if a.jpg:
                page.screenshot(path=str(out / f"{name}.jpg"), type="jpeg", quality=92)
            tmp.unlink(missing_ok=True)
            print("wrote", png)
        browser.close()
    print(f"done: {len(pages)} slides -> {out}")


if __name__ == "__main__":
    main()
