#!/usr/bin/env python3
"""
Client for the carpost Apps Script API (the only thing Claude talks to; the Telegram token stays in Apps Script).

env: CARPOST_API_URL  (the /exec URL)   CARPOST_API_TOKEN

CLI:
  python3 api.py ping
  python3 api.py bundle out.zip                       # download the code bundle
  python3 api.py claim RUN_ID                         # -> prints job json (or null)
  python3 api.py files JOB_ID DEST_DIR                # download all photos of a job
  python3 api.py upload JOB_ID RUN_ID FILE [NAME]     # upload one output file
  python3 api.py deliver JOB_ID RUN_ID caption.txt preview.jpg slide1.png slide2.png ...
  python3 api.py fail JOB_ID RUN_ID "error text"
  python3 api.py heartbeat JOB_ID RUN_ID
"""
import os, sys, json, base64, pathlib, urllib.request, urllib.parse, mimetypes, time

URL = os.environ.get("CARPOST_API_URL", "")
TOKEN = os.environ.get("CARPOST_API_TOKEN", "")


def _check():
    if not URL or not TOKEN:
        raise SystemExit("set CARPOST_API_URL and CARPOST_API_TOKEN")


def get(action, **params):
    _check()
    q = urllib.parse.urlencode(dict(api=TOKEN, action=action, **{k: v for k, v in params.items() if v is not None}))
    for attempt in range(3):
        try:
            with urllib.request.urlopen(URL + "?" + q, timeout=300) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def post(body):
    _check()
    data = json.dumps(body).encode()
    req = urllib.request.Request(URL + "?api=" + urllib.parse.quote(TOKEN), data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def ping():
    return get("ping")


def bundle(dest):
    d = get("bundle")
    if not d.get("ok"):
        raise SystemExit(d)
    raw = base64.b64decode(d["b64"])
    import hashlib
    if hashlib.sha256(raw).hexdigest() != d["sha256"]:
        raise SystemExit("bundle checksum mismatch")
    pathlib.Path(dest).write_bytes(raw)
    return {"name": d["name"], "size": d["size"], "sha256": d["sha256"]}


def claim(run_id):
    return get("claim", run=run_id)


def files(job_id, dest_dir):
    job = get("job", job=job_id)
    if not job.get("ok"):
        raise SystemExit(job)
    dest = pathlib.Path(dest_dir); dest.mkdir(parents=True, exist_ok=True)
    out = []
    for a in job["job"]["assets"]:
        d = get("file", job=job_id, idx=a["idx"])
        if not d.get("ok"):
            raise SystemExit(d)
        ext = pathlib.Path(d.get("name") or d.get("path") or "x.jpg").suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
            ext = ".jpg"
        p = dest / f"{int(a['idx']):02d}{ext}"
        p.write_bytes(base64.b64decode(d["b64"]))
        out.append(str(p))
        print("saved", p, d["size"], "bytes")
    (dest / "job.json").write_text(json.dumps(job["job"], ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def upload(job_id, run_id, path, name=None):
    p = pathlib.Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return post({"action": "upload", "job_id": job_id, "run_id": run_id, "name": name or p.name,
                 "mime": mime, "b64": base64.b64encode(p.read_bytes()).decode()})


def deliver(job_id, run_id, caption, slides, preview=None):
    return post({"action": "deliver", "job_id": job_id, "run_id": run_id, "caption": caption,
                 "slides": slides, "preview": preview})


def fail(job_id, run_id, error):
    return get("fail", job=job_id, run=run_id, error=error[:500])


def heartbeat(job_id, run_id):
    return get("heartbeat", job=job_id, run=run_id)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(0)
    cmd = a[0]
    if cmd == "ping":        print(json.dumps(ping(), ensure_ascii=False))
    elif cmd == "bundle":    print(json.dumps(bundle(a[1])))
    elif cmd == "claim":     print(json.dumps(claim(a[1]), ensure_ascii=False, indent=2))
    elif cmd == "files":     files(a[1], a[2])
    elif cmd == "upload":    print(json.dumps(upload(a[1], a[2], a[3], a[4] if len(a) > 4 else None)))
    elif cmd == "deliver":
        caption = pathlib.Path(a[3]).read_text(encoding="utf-8")
        print(json.dumps(deliver(a[1], a[2], caption, a[5:], pathlib.Path(a[4]).name), ensure_ascii=False))
    elif cmd == "fail":      print(json.dumps(fail(a[1], a[2], a[3]), ensure_ascii=False))
    elif cmd == "heartbeat": print(json.dumps(heartbeat(a[1], a[2])))
    else:
        print(__doc__); sys.exit(1)
