#!/usr/bin/env python3
"""
Car/background segmentation with onnxruntime only (no rembg, no OpenCV, no scipy).
Two models are combined (pixelwise AND) so stray objects that one model attaches to the car
fall back into the background. Models are downloaded lazily from rembg's GitHub release and
verified by SHA-256.

    from seg import car_mask
    mask = car_mask(pil_image)   # PIL 'L' mask, 255 = car
"""
import os, hashlib, pathlib, urllib.request, sys
import numpy as np
from PIL import Image, ImageFilter

MODEL_DIR = pathlib.Path(os.environ.get("CARPOST_MODELS", pathlib.Path.home() / ".carpost" / "models"))
MODELS = {
    "isnet": {
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
        "sha256": "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
        "size": (1024, 1024), "mean": (0.5, 0.5, 0.5), "std": (1.0, 1.0, 1.0),
    },
    "u2net": {
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
        "sha256": "8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491",
        "size": (320, 320), "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225),
    },
}
_sessions = {}


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(name):
    spec = MODELS[name]
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    dst = MODEL_DIR / f"{name}.onnx"
    if dst.exists() and _sha256(dst) == spec["sha256"]:
        return dst
    tmp = dst.with_suffix(".part")
    print(f"[seg] downloading {name} ...", file=sys.stderr)
    urllib.request.urlretrieve(spec["url"], tmp)
    got = _sha256(tmp)
    if got != spec["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{name}: checksum mismatch {got}")
    tmp.rename(dst)
    return dst


def _session(name):
    if name not in _sessions:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, os.cpu_count() or 1)
        _sessions[name] = ort.InferenceSession(str(ensure_model(name)), sess_options=opts,
                                               providers=["CPUExecutionProvider"])
    return _sessions[name]


def _predict(name, img):
    spec = MODELS[name]
    sess = _session(name)
    im = img.convert("RGB").resize(spec["size"], Image.Resampling.LANCZOS)
    a = np.asarray(im).astype(np.float32)
    a = a / max(float(a.max()), 1e-6)
    a = (a - np.array(spec["mean"], dtype=np.float32)) / np.array(spec["std"], dtype=np.float32)
    a = np.expand_dims(a.transpose(2, 0, 1), 0).astype(np.float32)
    out = sess.run(None, {sess.get_inputs()[0].name: a})[0]
    pred = out[:, 0, :, :]
    pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)
    m = Image.fromarray((np.squeeze(pred) * 255).astype("uint8"), mode="L")
    return m.resize(img.size, Image.Resampling.LANCZOS)


def _post(mask):
    """rembg-style clean-up: binary -> opening (radius 1) -> gaussian(sigma 2) -> threshold."""
    m = mask.point(lambda v: 255 if v >= 128 else 0)
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    m = m.filter(ImageFilter.GaussianBlur(2))
    return m.point(lambda v: 255 if v >= 127 else 0)


def car_mask(img, models=("isnet", "u2net"), grow=2):
    """PIL 'L' mask (255=car). AND of the models' masks, then grown back by `grow` px."""
    from PIL import ImageChops
    masks = [_post(_predict(n, img)) for n in models]
    m = masks[0]
    for other in masks[1:]:
        m = ImageChops.darker(m, other)
    if grow:
        m = m.filter(ImageFilter.MaxFilter(2 * grow + 1))
    return m


if __name__ == "__main__":
    import argparse, time
    ap = argparse.ArgumentParser()
    ap.add_argument("image"); ap.add_argument("--out", default=None)
    a = ap.parse_args()
    from PIL import ImageOps
    im = ImageOps.exif_transpose(Image.open(a.image)).convert("RGB")
    t = time.time()
    m = car_mask(im)
    print(f"mask in {time.time()-t:.1f}s, coverage {np.asarray(m).mean()/255:.2%}")
    if a.out:
        m.save(a.out)
