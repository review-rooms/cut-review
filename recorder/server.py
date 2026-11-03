"""cut-review local recorder: record how script lines should sound, straight into the room project.

claude.ai pages can't use the microphone, so this small server runs on the owner's own machine (in Docker, see
recorder/README.md) and serves one page that can. It lists the open notes on script lines (from the notes
`cut-review notes` saved) and keeps one take per note in .cut-review/takes/local/<note id>.<ext>, where
`cut-review takes` converts it. It answers only to localhost and never sends anything anywhere.

    python3 recorder/server.py ROOM_DIR [PORT]      # or ROOM=… PORT=… (the Docker image sets them)
"""
from __future__ import annotations

import http.server
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))   # the cut_review package, in a checkout
from cut_review.notes import saved_notes  # noqa: E402
from cut_review.room import Room, RoomError  # noqa: E402
from cut_review.takes import LOCAL, local_file, open_script_notes, private_dir, safe, take_row  # noqa: E402

PAGE = Path(__file__).resolve().parent / "page.html"
EXT = {"audio/webm": ".webm", "audio/mp4": ".m4a", "audio/ogg": ".ogg"}   # what browsers' MediaRecorder makes
TYPE = {v: k for k, v in EXT.items()}
MAX_BYTES = 20 * 1024 * 1024
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def open_notes(room_dir: Path) -> tuple[Room, dict[str, dict]]:
    room = Room.load(room_dir)
    cuts = {c["key"] for c in room.manifest.get("cuts", [])}
    return room, {n["id"]: n for n in open_script_notes(saved_notes(room), cuts)}


def take_info(room: Room, note: dict) -> dict | None:
    f = local_file(room, note)
    return {"type": TYPE.get(f.suffix, "application/octet-stream"), "bytes": f.stat().st_size} if f else None


def make_server(room_dir: Path, host: str = "0.0.0.0", port: int = 8790) -> http.server.ThreadingHTTPServer:
    room_dir = Path(room_dir).resolve()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, status: int, body: bytes = b"", typ: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def fail(self, status: int, message: str) -> None:
            self.send(status, json.dumps({"error": message}).encode())

        def guard(self) -> bool:
            # only the owner's own browser: a page on another site can't reach this through DNS tricks
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0] if not (self.headers.get("Host") or "").startswith("[") \
                else (self.headers.get("Host") or "").split("]")[0] + "]"
            if host not in LOCAL_HOSTS:
                self.fail(403, "the recorder only answers to localhost")
                return False
            return True

        def target(self) -> tuple[Room, dict] | None:
            """The open script note a /api/takes/<id> request is for, or None after answering 404/409."""
            nid = unquote(self.path.split("?", 1)[0][len("/api/takes/"):])
            try:
                room, notes = open_notes(room_dir)
            except RoomError as e:
                self.fail(409, str(e))
                return None
            if nid not in notes:
                self.fail(404, "no open script note with that id")
                return None
            return room, notes[nid]

        def do_GET(self):
            if not self.guard():
                return
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/notes":
                try:
                    room, notes = open_notes(room_dir)
                except RoomError as e:
                    self.fail(409, str(e))
                    return
                rows = [take_row(room, n) | {"note": n["id"], "take": take_info(room, n)} for n in notes.values()]
                order = {c["key"]: i for i, c in enumerate(room.manifest.get("cuts", []))}   # the room's order
                rows.sort(key=lambda r: (order.get(r["cut"], 1e9), r["line"]))
                self.send(200, json.dumps(rows).encode())
            elif path.startswith("/api/takes/"):
                t = self.target()
                if not t:
                    return
                f = local_file(*t)
                if not f:
                    self.fail(404, "no take for this note yet")
                    return
                self.send(200, f.read_bytes(), TYPE.get(f.suffix, "application/octet-stream"))
            else:
                self.fail(404, "not found")

        def do_PUT(self):
            if not self.guard():
                return
            if not self.path.startswith("/api/takes/"):
                self.fail(404, "not found")
                return
            t = self.target()
            if not t:
                return
            room, note = t
            typ = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if typ not in EXT:
                self.fail(415, "send audio/webm, audio/mp4 or audio/ogg")
                return
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_BYTES:
                while size > 0:   # read it away, so the browser gets the answer instead of a broken connection
                    size -= len(self.rfile.read(min(size, 1 << 20)) or b"\0" * size)
                self.fail(413, "too long: keep a take under a few minutes")
                return
            data = self.rfile.read(size)
            d = private_dir(room.state_dir / LOCAL)
            for old in d.glob(safe(note["id"]) + ".*"):   # one take per note: the new one replaces the old
                if old.name != ".gitignore":
                    old.unlink()
            (d / (safe(note["id"]) + EXT[typ])).write_bytes(data)
            self.send(200, json.dumps({"take": take_info(room, note)}).encode())

        def do_DELETE(self):
            if not self.guard():
                return
            if not self.path.startswith("/api/takes/"):
                self.fail(404, "not found")
                return
            t = self.target()
            if not t:
                return
            f = local_file(*t)
            if f:
                f.unlink()
            self.send(200, b"{}")

    return http.server.ThreadingHTTPServer((host, port), H)


if __name__ == "__main__":
    room_dir = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ROOM", "."))
    port = int(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("PORT", "8790"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Recorder for {room_dir.resolve()} on http://localhost:{port}/", flush=True)
    make_server(room_dir, host, port).serve_forever()
