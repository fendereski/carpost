#!/usr/bin/env bash
# Prepare a fresh container for the car-post pipeline. Idempotent. Prints timings.
# usage: bash bootstrap.sh [--models]   (--models also pre-downloads the segmentation models)
set -euo pipefail
cd "$(dirname "$0")"
T0=$(date +%s)
log(){ echo "[bootstrap $(( $(date +%s) - T0 ))s] $*"; }

log "python: $(python3 --version 2>&1)"
python3 -c "import numpy, PIL" 2>/dev/null || pip install --break-system-packages -q numpy pillow
python3 -c "import onnxruntime" 2>/dev/null || { log "installing onnxruntime"; pip install --break-system-packages -q onnxruntime==1.29.0; }
log "onnxruntime $(python3 -c 'import onnxruntime as o; print(o.__version__)')"
python3 -c "import pillow_heif" 2>/dev/null || pip install --break-system-packages -q pillow-heif || log "pillow-heif install failed (HEIC inputs will not open)"
python3 -c "from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); pg.set_content('<b>ok</b>'); b.close()
print('playwright + chromium ok')" || { log "playwright missing -> installing"; pip install --break-system-packages -q playwright && python3 -m playwright install chromium; }
# --- assets that are not kept in the git repo as binaries ---
if ! ls fonts/*.woff2 >/dev/null 2>&1; then
  log "fonts missing -> fetching Vazirmatn from npm"
  mkdir -p fonts _npm && ( cd _npm && npm pack vazirmatn --silent >/dev/null 2>&1 && tar xzf vazirmatn-*.tgz )
  for w in Regular Medium Bold Black; do cp "_npm/package/fonts/webfonts/Vazirmatn-$w.woff2" fonts/; done
  rm -rf _npm
fi
log "fonts: $(ls fonts/*.woff2 | wc -l) files"
if ! ls brand/*.png >/dev/null 2>&1 && [[ -n "${CARPOST_API_URL:-}" && -n "${CARPOST_API_TOKEN:-}" ]]; then
  log "brand logos missing -> extracting brand/*.png from the Apps Script bundle (data only)"
  python3 - <<'PY' || log "could not fetch brand logos (slides will show the brand name as text)"
import os, json, base64, hashlib, io, zipfile, urllib.request
u = os.environ["CARPOST_API_URL"] + "?api=" + os.environ["CARPOST_API_TOKEN"] + "&action=bundle"
d = json.load(urllib.request.urlopen(u, timeout=120))
b = base64.b64decode(d["b64"]); assert hashlib.sha256(b).hexdigest() == d["sha256"]
z = zipfile.ZipFile(io.BytesIO(b)); os.makedirs("brand", exist_ok=True)
for n in z.namelist():
    if n.startswith("brand/") and n.endswith(".png"):
        open(n, "wb").write(z.read(n)); print("extracted", n)
PY
fi
log "brand logos: $(ls brand/*.png 2>/dev/null | wc -l) files"
if [[ "${1:-}" == "--models" ]]; then
  python3 -c "import seg; [seg.ensure_model(n) for n in ('isnet','u2net')]; print('models ok')"
  log "models ready"
fi
log "done"
