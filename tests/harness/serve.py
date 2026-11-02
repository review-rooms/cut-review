"""Serve the review page locally against a stand-in for claude.ai's data layer, to test the page in a browser.

    python3 tests/harness/serve.py <room folder> [port]

The room folder must have been built (`cut-review build`): its records in `.cut-review/out/` seed the stand-in
database, and `/_blob/<id>` serves the local file that `.cut-review/state.json` maps to that asset id, with byte
ranges so videos seek. Notes and verdicts written on the page live in memory until the page reloads;
`window.__store` exposes the data for checks, `window.__downloads` the files the Download button saved.
Files the page uploads (voice takes) go to `.cut-review/harness-assets/` and are served at `/_blob/<id>` too;
`window.__assets` lists uploads and deletions. `?noassets` / `?nodownloads` leave those capabilities out.
`?mic=fake` gives the page a microphone that plays a tone (as if the frame allowed the mic); `?mic=blocked`
answers like claude.ai today (permission denied).
Nothing here talks to claude.ai.
"""
from __future__ import annotations

import http.server
import json
import mimetypes
import re
import secrets
import sys
from urllib.parse import parse_qs
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent.parent / "src" / "cut_review" / "page" / "review-room.html"

MOCK = r"""<script>
(() => {
  const store = __SEED__;
  for (const c of ["room", "cuts", "sets", "notes", "verdicts"]) store[c] = store[c] || {};
  const subs = [];
  const fire = () => setTimeout(() => subs.forEach((f) => f()), 15);
  const snapDoc = (c, id) => ({ id, exists: !!store[c][id], data: () => store[c][id], metadata: { fromCache: false, hasPendingWrites: false } });
  const docRef = (c, id) => ({
    id, path: c + "/" + id,
    onSnapshot(next) { const f = () => next(snapDoc(c, id)); subs.push(f); setTimeout(f, 20); return () => {}; },
    async get() { return snapDoc(c, id); },
    async set(d) { store[c][id] = JSON.parse(JSON.stringify(d)); fire(); },
    async update(d) { if (!store[c][id]) throw { code: "invalid_argument", message: "no such document" }; Object.assign(store[c][id], d); fire(); },
    async delete() { delete store[c][id]; fire(); },
  });
  const coll = (c) => ({
    path: c,
    onSnapshot(next) {
      const f = () => { const docs = Object.keys(store[c]).sort().map((id) => snapDoc(c, id)); next({ docs, size: docs.length, empty: !docs.length, docChanges: () => [], metadata: {} }); };
      subs.push(f); setTimeout(f, 20); return () => {};
    },
    doc: (id) => docRef(c, id || Math.random().toString(36).slice(2, 12)),
    async add(d) { const id = Math.random().toString(36).slice(2, 12); store[c][id] = JSON.parse(JSON.stringify(d)); fire(); return docRef(c, id); },
  });
  const db = { collection: coll, doc: (p) => { const [c, id] = p.split("/"); return docRef(c, id); } };
  const user = { id: async () => "u_harness", can: async () => true, isOwner: async () => true, canEdit: async () => true };
  window.__store = store;
  window.__db = db;
  // `downloads` stand-in: records each save in window.__downloads; `?nodownloads` leaves it out (the page's fallback)
  window.__downloads = [];
  const downloads = location.search.includes("nodownloads") ? null : {
    save: async ({ filename, data }) => { window.__downloads.push({ filename, size: data.size ?? data.length }); return { status: "saved" }; },
  };
  // `assets` stand-in: uploads go to the server (saved under .cut-review/harness-assets/, served at /_blob/<id>)
  window.__assets = [];
  const assets = location.search.includes("noassets") ? null : {
    async upload(blob, opts) {
      const type = (opts && opts.type) || blob.type;
      if (!["video/mp4", "video/webm"].includes(type) && !/^image\//.test(type)) throw { code: "unsupported_type", message: type };
      if (blob.size > 20 * 1024 * 1024) throw { code: "too_large", message: String(blob.size) };
      const r = await fetch("/_assets?type=" + encodeURIComponent(type), { method: "POST", body: blob });
      const a = await r.json();
      window.__assets.push({ op: "upload", ...a });
      return a;
    },
    async delete(id) { await fetch("/_assets?delete=" + id, { method: "POST" }); window.__assets.push({ op: "delete", id }); },
  };
  // microphone stand-ins: claude.ai blocks the mic in its frames, so the page must also work without one
  const mic = (location.search.match(/mic=(\w+)/) || [])[1];
  if (mic === "fake" || mic === "blocked") {
    const realQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (d) => d && d.name === "microphone" ? Promise.resolve({ state: mic === "fake" ? "prompt" : "denied" }) : realQuery(d);
    navigator.mediaDevices.getUserMedia = async () => {
      if (mic === "blocked") throw Object.assign(new Error("Permission denied"), { name: "NotAllowedError" });
      const ac = new AudioContext(); await ac.resume();
      const osc = ac.createOscillator(), dest = ac.createMediaStreamDestination();
      osc.frequency.value = 330; osc.connect(dest); osc.start();
      return dest.stream;
    };
  }
  const caps = { db, user, downloads, assets };
  window.claude = { use: (n) => new Promise((r) => setTimeout(() => r(caps[n] ?? null), 30)) };
})();
</script>
"""

SKELETON = ('<!doctype html><html><head><meta charset=utf-8>'
            '<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>:root{color-scheme:light}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
            '</head><body>')


def seed(room: Path) -> dict:
    store: dict[str, dict] = {}
    for f in sorted((room / ".cut-review" / "out").glob("*__*.json")):
        coll, doc = f.stem.split("__", 1)
        if coll == "notes":
            continue
        store.setdefault(coll, {})[doc] = json.loads(f.read_text())
    return store


def blobs(room: Path) -> dict[str, Path]:
    state = json.loads((room / ".cut-review" / "state.json").read_text())
    manifest = json.loads((room / "room.json").read_text())
    media = Path(manifest.get("media", ".")).expanduser()
    root = (media if media.is_absolute() else room / media).resolve()
    return {rec["id"]: root / rel for rel, rec in state.get("files", {}).items() if rec.get("id")}


def handler(room: Path):
    files = blobs(room)
    uploads = room / ".cut-review" / "harness-assets"
    types: dict[str, str] = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            path, _, query = self.path.partition("?")
            q = parse_qs(query)
            if path != "/_assets":
                self.send_error(404)
                return
            if "delete" in q:
                i = q["delete"][0]
                if re.fullmatch(r"[0-9a-f]{32}", i):
                    (uploads / i).unlink(missing_ok=True)
                    files.pop(i, None)
                body = b"{}"
            else:
                data = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                i, typ = secrets.token_hex(16), q.get("type", ["application/octet-stream"])[0]
                uploads.mkdir(parents=True, exist_ok=True)
                (uploads / i).write_bytes(data)
                files[i], types[i] = uploads / i, typ
                body = json.dumps({"id": i, "url": f"/_blob/{i}", "sizeBytes": len(data), "contentType": typ}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                body = (SKELETON + MOCK.replace("__SEED__", json.dumps(seed(room))) + PAGE.read_text() + "</body></html>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            m = re.fullmatch(r"/_blob/([0-9a-f]+)", path)
            f = files.get(m.group(1)) if m else None
            if not f or not f.is_file():
                self.send_error(404)
                return
            size = f.stat().st_size
            start, end = 0, size - 1
            rng = self.headers.get("Range")
            r = re.match(r"bytes=(\d*)-(\d*)", rng or "")
            if r:
                start = int(r.group(1) or 0)
                end = int(r.group(2)) if r.group(2) else size - 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", types.get(m.group(1)) or mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 16, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

    return H


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    room = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    print(f"Review page for {room} on http://127.0.0.1:{port}/", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler(room)).serve_forever()
