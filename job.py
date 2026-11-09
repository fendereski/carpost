#!/usr/bin/env python3
"""
One-job orchestration for the car-post pipeline (used by Claude in a manual run).

  python3 job.py start                 -> claims the next ready job, downloads its photos into jobs/<code>/photos/,
                                          writes jobs/<code>/job.json, builds gridded contact sheets
                                          (photos/_grid1.jpg ...) and prints what Claude must do next.
  python3 job.py render  jobs/<code>   -> renders jobs/<code>/car.json into jobs/<code>/out/ and writes the preview
                                          sheet out/<code>_preview.jpg (look at it: crops fine? subject intact?).
  python3 job.py deliver jobs/<code>   -> uploads slides + preview, delivers to Telegram (via Apps Script),
                                          marks the job delivered. Prints DELIVERED.
  python3 job.py finish  jobs/<code>   -> render + deliver in one go (no visual check).
  python3 job.py fail    jobs/<code> "reason"

Claude's only creative step sits between start and render: write jobs/<code>/car.json and jobs/<code>/caption.txt
(see RULES.md / RUN.md). Everything else is mechanical.
"""
import sys, os, json, pathlib, subprocess, time, random
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api

JOBS = HERE / "jobs"


def start():
    run_id = f"{int(time.time())}-{random.randint(1000, 9999)}"
    res = api.claim(run_id)
    if not res.get("ok"):
        raise SystemExit(res)
    job = res["job"]
    if not job:
        print("NO_JOB"); return
    code = str(job["code"]).zfill(3)
    d = JOBS / code
    (d / "photos").mkdir(parents=True, exist_ok=True)
    job["run_id"] = run_id
    (d / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = api.files(job["job_id"], d / "photos")
    grids = make_grids([pathlib.Path(p) for p in paths], d / "photos")
    print("\n=== JOB CLAIMED ===")
    print("code:", code, "| job_id:", job["job_id"], "| run_id:", run_id)
    print("dir :", d)
    print("specs (from user):\n" + (job.get("specs") or "").strip())
    print("photos:", *paths, sep="\n  ")
    print("grids :", *grids, sep="\n  ")
    print("\nNEXT: Read the grid sheets (every photo, with a 10% grid), then write", d / "car.json", "and",
          d / "caption.txt", "per RUN.md; then: python3 job.py render", d, "-> check the preview -> python3 job.py deliver", d)


def make_grids(paths, dest, per_sheet=4, tile_w=800):
    """Contact sheets of the job photos with a 10 % grid (numbers 1-9 on both axes) so keep_x / keep_y can be
    read off as fractions. 2x2 photos per sheet, written as dest/_grid1.jpg, _grid2.jpg ..."""
    from PIL import Image, ImageDraw, ImageOps
    sheets = []
    paths = [p for p in paths if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".webp") and not p.name.startswith("_")]
    for n, i in enumerate(range(0, len(paths), per_sheet), start=1):
        tiles = []
        for p in paths[i:i + per_sheet]:
            try:
                im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            except Exception:
                try:
                    import pillow_heif; pillow_heif.register_heif_opener()
                    im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
                except Exception as e:
                    print("grid: cannot open", p, e); continue
            im.thumbnail((tile_w, tile_w))
            W, H = im.size
            dr = ImageDraw.Draw(im)
            for k in range(1, 10):
                x, y = int(W * k / 10), int(H * k / 10)
                dr.line([(x, 0), (x, H)], fill=(255, 40, 40), width=1)
                dr.line([(0, y), (W, y)], fill=(255, 40, 40), width=1)
                dr.text((x + 3, 3), str(k), fill=(255, 255, 0)); dr.text((3, y + 3), str(k), fill=(255, 255, 0))
            dr.rectangle((0, H - 18, 8 * len(p.name) + 8, H), fill=(0, 0, 0))
            dr.text((4, H - 16), p.name, fill=(0, 255, 255))
            tiles.append(im)
        if not tiles:
            continue
        cols = 2 if len(tiles) > 1 else 1
        rows = (len(tiles) + cols - 1) // cols
        cw, ch = max(t.width for t in tiles), max(t.height for t in tiles)
        sheet = Image.new("RGB", (cw * cols, ch * rows), (24, 24, 24))
        for j, t in enumerate(tiles):
            sheet.paste(t, ((j % cols) * cw, (j // cols) * ch))
        out = pathlib.Path(dest) / f"_grid{n}.jpg"
        sheet.save(out, quality=85)
        sheets.append(str(out))
    return sheets


def _load(jobdir):
    d = pathlib.Path(jobdir)
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    return d, job, str(job["code"]).zfill(3)


def render(jobdir):
    """Render car.json -> out/0N-*.png + out/<code>_preview.jpg. Safe to run again after editing car.json."""
    d, job, code = _load(jobdir)
    car_path, cap_path = d / "car.json", d / "caption.txt"
    if not car_path.exists() or not cap_path.exists():
        raise SystemExit("car.json / caption.txt missing")
    car = json.loads(car_path.read_text(encoding="utf-8"))
    car["code"] = code
    car["slug"] = f"code-{code}"
    for k in ("fit", "cover_fit", "focus", "title_bottom"):   # crop decisions belong to the code
        car.pop(k, None)
    car_path.write_text(json.dumps(car, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        api.heartbeat(job["job_id"], job["run_id"])
    except (Exception, SystemExit) as e:
        print("heartbeat skipped:", e)

    out = d / "out"
    for old in out.glob("*.png"):
        old.unlink()
    subprocess.run([sys.executable, str(HERE / "render.py"), str(car_path), "--out", str(out)], check=True, cwd=str(HERE))
    slides = sorted(out.glob("[0-9][0-9]-*.png"))
    if len(slides) < 2:
        raise SystemExit("render produced <2 slides")
    from PIL import Image
    w, h, cols, pad = 360, 450, 3, 16
    rows_ = (len(slides) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w + (cols + 1) * pad, rows_ * h + (rows_ + 1) * pad), (245, 245, 245))
    for i, p in enumerate(slides):
        sheet.paste(Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS), (pad + (i % cols) * (w + pad), pad + (i // cols) * (h + pad)))
    preview = out / f"{code}_preview.jpg"
    sheet.save(preview, quality=88)
    print(f"RENDERED {len(slides)} slides")
    print("PREVIEW", preview)
    print("NEXT: Read the preview (car not cut? interior subject inside the frame? black bands only on interiors?). Fix car.json and re-run render if needed, then: python3 job.py deliver", d)
    return slides, preview


def deliver(jobdir):
    """Upload the rendered slides + preview and deliver via Apps Script (Telegram)."""
    d, job, code = _load(jobdir)
    out = d / "out"
    slides = sorted(out.glob("[0-9][0-9]-*.png"))
    preview = out / f"{code}_preview.jpg"
    if len(slides) < 2 or not preview.exists():
        raise SystemExit("nothing rendered yet: run `python3 job.py render` first")
    names = []
    for i, p in enumerate(slides, start=1):
        name = f"{code}_{i:02d}.png"
        r = api.upload(job["job_id"], job["run_id"], p, name)
        if not r.get("ok"):
            raise SystemExit(f"upload failed {name}: {r}")
        names.append(name); print("uploaded", name, r.get("size"))
    r = api.upload(job["job_id"], job["run_id"], preview, preview.name)
    if not r.get("ok"):
        raise SystemExit(f"upload failed preview: {r}")
    caption = (d / "caption.txt").read_text(encoding="utf-8").strip()
    r = api.deliver(job["job_id"], job["run_id"], caption, names, preview.name)
    if not r.get("ok"):
        raise SystemExit(f"deliver failed: {r}")
    print("DELIVERED code", code, "messages:", r.get("message_ids"))


def finish(jobdir):
    render(jobdir)
    deliver(jobdir)


def fail(jobdir, reason):
    job = json.loads((pathlib.Path(jobdir) / "job.json").read_text(encoding="utf-8"))
    print(api.fail(job["job_id"], job["run_id"], reason))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(0)
    if a[0] == "start": start()
    elif a[0] == "render": render(a[1])
    elif a[0] == "deliver": deliver(a[1])
    elif a[0] == "finish": finish(a[1])
    elif a[0] == "grid": print(*make_grids(sorted(pathlib.Path(a[1]).glob("*")), a[1]), sep="\n")
    elif a[0] == "fail": fail(a[1], a[2] if len(a) > 2 else "unknown error")
    else: print(__doc__); sys.exit(1)
