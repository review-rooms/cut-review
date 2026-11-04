"""The local recorder (recorder/server.py): lists open script notes, keeps one take per note in .cut-review/takes/local/."""
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from cut_review.notes import load_export, save_notes
from cut_review.room import Room

spec = importlib.util.spec_from_file_location("recorder_server", Path(__file__).parent.parent / "recorder" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


@pytest.fixture
def room(tmp_path: Path) -> Path:
    manifest = {"title": "Rec room", "media": ".", "cuts": [
        {"key": "poll", "file": "poll.mp4", "script": [{"from": 0, "to": 3, "text": "Where [pause] should you go?"}]}]}
    (tmp_path / "room.json").write_text(json.dumps(manifest))
    d = tmp_path / "export"
    d.mkdir()
    docs = {
        "w": {"cut": "poll", "t": 0, "line": 0, "quote": "should", "qStart": 6, "qEnd": 12, "text": "Rise here", "status": "open"},
        "r": {"cut": "poll", "t": 0, "line": 0, "text": "Done", "status": "resolved"},
        "t": {"cut": "poll", "t": 5, "text": "Not on the script", "status": "open"},
    }
    for k, v in docs.items():
        (d / f"{k}.json").write_text(json.dumps({"id": k, "version": 1, "data": v}))
    save_notes(Room.load(tmp_path), load_export(d))
    return tmp_path


@pytest.fixture
def url(room):
    srv = server.make_server(room, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(url, path, method="GET", body=None, headers=None):
    req = urllib.request.Request(url + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def test_lists_open_script_notes_with_their_words(url):
    status, typ, body = call(url, "/api/notes")
    assert status == 200 and typ.startswith("application/json")
    notes = json.loads(body)
    assert [n["note"] for n in notes] == ["w"]
    want = {"cut": "poll", "line": 0, "from": 0, "to": 3, "text": "Where should you go?", "words": "should",
            "noteText": "Rise here", "take": None}
    assert {k: notes[0][k] for k in want} == want


def test_lists_notes_in_the_rooms_cut_order(room):
    m = json.loads((room / "room.json").read_text())
    m["cuts"].insert(0, {"key": "zz", "file": "zz.mp4", "script": [{"from": 0, "to": 1, "text": "First cut"}]})
    (room / "room.json").write_text(json.dumps(m))
    notes = json.loads((room / ".cut-review" / "notes.json").read_text())
    notes.append({"id": "z", "cut": "zz", "line": 0, "text": "On the first cut", "status": "open", "dbVersion": 1})
    (room / ".cut-review" / "notes.json").write_text(json.dumps(notes))
    srv = server.make_server(room, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rows = json.loads(call(f"http://127.0.0.1:{srv.server_address[1]}", "/api/notes")[2])
    finally:
        srv.shutdown()
    assert [r["note"] for r in rows] == ["z", "w"]


def test_keeps_one_take_per_note_and_plays_it_back(url, room):
    local = room / ".cut-review" / "takes" / "local"
    assert call(url, "/api/takes/w", "PUT", b"webm-bytes", {"Content-Type": "audio/webm;codecs=opus"})[0] == 200
    assert (local / "w.webm").read_bytes() == b"webm-bytes" and (local / ".gitignore").read_text() == "*\n"
    assert json.loads(call(url, "/api/notes")[2])[0]["take"] == {"type": "audio/webm", "bytes": 10}
    assert call(url, "/api/takes/w", "PUT", b"m4a", {"Content-Type": "audio/mp4"})[0] == 200
    assert sorted(p.name for p in local.iterdir()) == [".gitignore", "w.m4a"]      # the new take replaces the old one
    status, typ, body = call(url, "/api/takes/w")
    assert (status, typ, body) == (200, "audio/mp4", b"m4a")
    assert call(url, "/api/takes/w", "DELETE")[0] == 200 and not (local / "w.m4a").exists()
    assert call(url, "/api/takes/w")[0] == 404


def test_refuses_takes_for_other_notes_types_and_sizes(url, room):
    assert call(url, "/api/takes/r", "PUT", b"x", {"Content-Type": "audio/webm"})[0] == 404     # resolved
    assert call(url, "/api/takes/t", "PUT", b"x", {"Content-Type": "audio/webm"})[0] == 404     # not on the script
    assert call(url, "/api/takes/..%2Fx", "PUT", b"x", {"Content-Type": "audio/webm"})[0] == 404
    assert call(url, "/api/takes/w", "PUT", b"x", {"Content-Type": "text/html"})[0] == 415
    assert call(url, "/api/takes/w", "PUT", b"x" * (20 * 1024 * 1024 + 1), {"Content-Type": "audio/webm"})[0] == 413
    assert not list((room / ".cut-review").glob("takes/local/[wrt].*"))   # nothing was saved


def test_answers_only_to_localhost(url):
    assert call(url, "/api/notes", headers={"Host": "evil.example:8790"})[0] == 403
    assert call(url, "/api/notes", headers={"Host": "localhost:8790"})[0] == 200


def test_serves_the_page_and_says_when_notes_are_missing(url, room):
    status, typ, body = call(url, "/")
    assert status == 200 and typ.startswith("text/html") and body.startswith(b"<!doctype html>")
    (room / ".cut-review" / "notes.json").unlink()
    status, _, body = call(url, "/api/notes")
    assert status == 409 and b"cut-review notes" in body
