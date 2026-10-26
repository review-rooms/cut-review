import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cut_review import cli
from cut_review.notes import extract_frames, fix_writes, load_export, region_of, save_notes, todo, where
from cut_review.parse import parse_assets, parse_listed_versions, parse_written
from cut_review.records import build_records, chunks, confirm, stage
from cut_review.room import Room, RoomError

NO_PROBE = lambda p: None  # noqa: E731


@pytest.fixture
def room_dir(tmp_path: Path) -> Path:
    media = tmp_path / "media"
    (media / "carousel").mkdir(parents=True)
    (media / "poll.mp4").write_bytes(b"video-1")
    (media / "poll.poster.png").write_bytes(b"poster-1")
    (media / "carousel" / "01-hook.png").write_bytes(b"still")
    (media / "carousel" / "02-clip.mp4").write_bytes(b"clip")
    manifest = {
        "title": "Test room", "media": "media", "groups": [{"id": "week", "label": "Week one"}],
        "cuts": [{"key": "poll", "file": "poll.mp4", "poster": "poll.poster.png", "group": "week",
                  "tags": ["engagement"], "length": 40.6, "script": [{"from": 0, "to": 3, "text": "Hook"}]}],
        "sets": [{"key": "carousel", "dir": "carousel", "group": "week", "aspect": "4:5"}],
    }
    (tmp_path / "room.json").write_text(json.dumps(manifest))
    return tmp_path


def upload_text(room_dir: Path, ids: dict[str, str]) -> str:
    lines = ["Assets uploaded: n of n files are now stored in the artifact."]
    for rel, i in ids.items():
        lines.append(f'- "{room_dir / "media" / rel}" (10 bytes, video/mp4) → "/_blob/{i}" (id {i})')
    return "\n".join(lines)


ALL = {"poll.mp4": "a" * 32, "poll.poster.png": "b" * 32, "carousel/01-hook.png": "c" * 32, "carousel/02-clip.mp4": "d" * 32}


def run(room_dir, *args):
    return cli.main(["-C", str(room_dir), *args])


def uploaded(room_dir, capsys):
    (room_dir / "up.txt").write_text(upload_text(room_dir, ALL))
    assert run(room_dir, "assets", str(room_dir / "up.txt")) == 0
    capsys.readouterr()


# ---------------------------------------------------------------- parsers
def test_parse_assets_reads_tool_text_and_json():
    text = ('- "/x/poll.mp4" (4640162 bytes, video/mp4) → "/_blob/156dc67f538f092e0093aff2ca858328" (id 156dc67f538f092e0093aff2ca858328)\n'
            '- "/x/a b.png" (1 bytes, image/png) -> "/_blob/0123456789abcdef0123456789abcdef" (id 0123456789abcdef0123456789abcdef)')
    assert parse_assets(text) == {"/x/poll.mp4": "156dc67f538f092e0093aff2ca858328", "/x/a b.png": "0123456789abcdef0123456789abcdef"}
    assert parse_assets('{"/x/poll.mp4": "/_blob/' + "e" * 32 + '"}') == {"/x/poll.mp4": "e" * 32}
    assert parse_assets('[{"path": "/x/p.mp4", "id": "' + "f" * 32 + '"}]') == {"/x/p.mp4": "f" * 32}


def test_parse_listed_versions_reads_out_dir_results():
    text = ('1 document from collection "notes" saved as JSON files under "/x/export/notes":\n'
            '- "probe-cli-check"  239 bytes  version 1  "/x/export/notes/probe-cli-check.json"\n'
            '- "k3Jx9"  301 bytes  version 4  "/x/export/notes/k3Jx9.json"')
    assert parse_listed_versions(text) == {"probe-cli-check": 1, "k3Jx9": 4}


def test_notes_command_takes_versions_from_the_list_result(room_dir, tmp_path, capsys):
    e = export(tmp_path, {"n1": {"cut": "poll", "t": 9.2, "text": "Late", "status": "open", "version": 1}})
    (tmp_path / "result.txt").write_text('- "n1"  200 bytes  version 6  "/x/n1.json"')
    assert run(room_dir, "notes", str(e), "--result", str(tmp_path / "result.txt")) == 0
    saved = json.loads((room_dir / ".cut-review" / "notes.json").read_text())
    assert saved[0]["dbVersion"] == 6 and saved[0]["version"] == 1  # the cut version stays the note's own field


def test_parse_written_reads_batch_results():
    text = ('Database batch committed atomically — 3 writes;\n- set "cuts"/"poll" (version 1)\n'
            '- update "notes"/"n1" (version 4)\n- delete "verdicts"/"poll"')
    assert parse_written(text) == [
        {"op": "set", "collection": "cuts", "doc_id": "poll", "version": 1},
        {"op": "update", "collection": "notes", "doc_id": "n1", "version": 4},
        {"op": "delete", "collection": "verdicts", "doc_id": "poll", "version": None},
    ]


# ---------------------------------------------------------------- manifest
def test_manifest_rejects_bad_and_duplicate_keys(tmp_path):
    (tmp_path / "room.json").write_text(json.dumps({"cuts": [{"key": "a/b", "file": "x.mp4"}]}))
    with pytest.raises(RoomError, match="letters"):
        Room.load(tmp_path)
    (tmp_path / "room.json").write_text(json.dumps({"cuts": [{"key": "a", "file": "x.mp4"}], "sets": [{"key": "a", "dir": "d"}]}))
    with pytest.raises(RoomError, match="twice"):
        Room.load(tmp_path)


def test_init_lists_videos_posters_and_sets(room_dir, capsys):
    (room_dir / "room.json").unlink()
    assert run(room_dir, "init", "--media", "media", "--title", "T") == 0
    m = json.loads((room_dir / "room.json").read_text())
    assert [c["key"] for c in m["cuts"]] == ["poll"]
    assert m["cuts"][0]["poster"] == "poll.poster.png"
    assert m["sets"] == [{"key": "carousel", "dir": "carousel", "title": "Carousel", "group": "sets", "aspect": "4:5", "description": ""}]
    assert run(room_dir, "init") == 1  # refuses to overwrite


# ---------------------------------------------------------------- uploads
def test_uploads_lists_new_files_then_only_changed_ones(room_dir, capsys):
    run(room_dir, "uploads", "--json")
    batches = json.loads(capsys.readouterr().out)["batches"]
    assert len(batches) == 1 and len(batches[0]) == 4
    uploaded(room_dir, capsys)
    run(room_dir, "uploads", "--json")
    assert json.loads(capsys.readouterr().out)["batches"] == []
    (room_dir / "media" / "poll.mp4").write_bytes(b"video-2")
    run(room_dir, "uploads", "--json")
    assert json.loads(capsys.readouterr().out)["batches"] == [[str(room_dir / "media" / "poll.mp4")]]


def test_uploads_split_in_batches_of_25(tmp_path, capsys):
    (tmp_path / "s").mkdir()
    for i in range(30):
        (tmp_path / "s" / f"{i:02d}.png").write_bytes(bytes([i]))
    (tmp_path / "room.json").write_text(json.dumps({"sets": [{"key": "s", "dir": "s"}]}))
    run(tmp_path, "uploads", "--json")
    assert [len(b) for b in json.loads(capsys.readouterr().out)["batches"]] == [25, 5]


def test_assets_ignores_files_outside_the_room(room_dir, capsys):
    (room_dir / "up.txt").write_text('- "/elsewhere/x.mp4" (1 bytes, video/mp4) → "/_blob/' + "a" * 32 + '" (id x)')
    run(room_dir, "assets", str(room_dir / "up.txt"))
    assert "ignored" in capsys.readouterr().out
    assert Room.load(room_dir).state["files"] == {}


# ---------------------------------------------------------------- records and versions
def test_build_refuses_until_everything_is_uploaded(room_dir):
    with pytest.raises(RoomError, match="not uploaded yet"):
        build_records(Room.load(room_dir), probe=NO_PROBE)


def test_build_records_shape(room_dir, capsys):
    uploaded(room_dir, capsys)
    recs = {f"{c}/{d}": data for c, d, data, _ in build_records(Room.load(room_dir), probe=NO_PROBE)}
    assert recs["room/meta"]["title"] == "Test room"
    assert recs["room/meta"]["groups"] == [{"id": "week", "label": "Week one"}]
    poll = recs["cuts/poll"]
    assert poll["video"] == "/_blob/" + "a" * 32 and poll["poster"] == "/_blob/" + "b" * 32
    assert poll["version"] == 1 and poll["changes"] == [] and poll["order"] == 0 and poll["length"] == 40.6
    assert recs["sets/carousel"]["items"] == [
        {"name": "01-hook", "kind": "still", "url": "/_blob/" + "c" * 32},
        {"name": "02-clip", "kind": "clip", "url": "/_blob/" + "d" * 32},
    ]
    assert recs["sets/carousel"]["order"] == 1


def test_version_bumps_once_per_new_asset_and_only_after_written(room_dir, capsys):
    uploaded(room_dir, capsys)
    room = Room.load(room_dir)
    writes = stage(room, build_records(room, probe=NO_PROBE))
    assert [w["doc_id"] for w in writes] == ["meta", "poll", "carousel"]
    assert all("if_version" not in w for w in writes)
    confirm(room, parse_written('- set "room"/"meta" (version 1)\n- set "cuts"/"poll" (version 1)\n- set "sets"/"carousel" (version 1)'))
    room.save()

    # unchanged: nothing to write
    room = Room.load(room_dir)
    assert stage(room, build_records(room, probe=NO_PROBE)) == []

    # a re-render under a new id: v2 with the change note, pinned to db version 1
    room.state["files"]["poll.mp4"] = {"id": "9" * 32, "sha256": "x"}
    recs = build_records(room, {"poll": "Counter pops earlier"}, probe=NO_PROBE)
    poll = next(d for c, k, d, _ in recs if k == "poll")
    assert poll["version"] == 2 and poll["changes"] == [{"v": 2, "note": "Counter pops earlier"}]
    writes = stage(room, recs)
    assert writes == [{"op": "set", "collection": "cuts", "doc_id": "poll", "file_path": writes[0]["file_path"], "if_version": 1}]

    # building again before the write is confirmed does not bump twice
    again = next(d for c, k, d, _ in build_records(room, probe=NO_PROBE) if k == "poll")
    assert again["version"] == 2
    confirm(room, parse_written('- set "cuts"/"poll" (version 2)'))
    conf = room.state["records"]["cuts/poll"]["confirmed"]
    assert conf["version"] == 2 and conf["db"] == 2 and "pending" not in room.state["records"]["cuts/poll"]


def test_chunks_respect_the_batch_limit():
    assert [len(c) for c in chunks([{}] * 120)] == [50, 50, 20]


# ---------------------------------------------------------------- notes and fixes
def export(tmp_path: Path, docs: dict[str, dict]) -> Path:
    d = tmp_path / "export" / "notes"
    d.mkdir(parents=True)
    for name, obj in docs.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return tmp_path / "export"


def test_load_export_accepts_wrapped_and_raw_documents(tmp_path):
    e = export(tmp_path, {
        "n1": {"id": "n1", "version": 3, "data": {"cut": "poll", "t": 9.2, "text": "Late", "status": "open"}},
        "n2": {"cut": "carousel", "t": None, "item": "01-hook", "text": "Busy", "status": "fixed"},
        "junk": {"hello": 1},
    })
    notes = {n["id"]: n for n in load_export(e)}
    assert set(notes) == {"n1", "n2"}
    assert notes["n1"]["dbVersion"] == 3 and notes["n1"]["t"] == 9.2
    assert notes["n2"]["dbVersion"] is None and notes["n2"]["item"] == "01-hook"


def test_todo_groups_by_room_order_and_lists_open_only(room_dir, tmp_path):
    room = Room.load(room_dir)
    notes = load_export(export(tmp_path, {
        "b": {"id": "b", "version": 1, "data": {"cut": "carousel", "item": "01-hook", "text": "Busy", "status": "open"}},
        "a2": {"id": "a2", "version": 1, "data": {"cut": "poll", "t": 20, "text": "Later one", "status": "open"}},
        "a1": {"id": "a1", "version": 1, "data": {"cut": "poll", "t": 3.25, "text": "Early one", "status": "open"}},
        "r": {"id": "r", "version": 1, "data": {"cut": "poll", "t": 1, "text": "Done", "status": "resolved"}},
    }))
    out = todo(room, notes)
    assert out.startswith("# Notes: 3 open, 0 fixed")
    assert out.index("## poll") < out.index("## carousel")
    assert out.index("0:03.2 · Early one") < out.index("0:20.0 · Later one")
    assert "Done" not in out and "Done" in todo(room, notes, show_all=True)


def test_todo_shows_time_ranges_and_regions(room_dir, tmp_path):
    room = Room.load(room_dir)
    notes = load_export(export(tmp_path, {
        "rg": {"id": "rg", "version": 1, "data": {"cut": "poll", "t": 2, "tEnd": 4.5, "text": "Too slow", "status": "open"}},
        "bx": {"id": "bx", "version": 1, "data": {"cut": "poll", "t": 6, "region": {"x": 0.1, "y": 0.25, "w": 0.5, "h": 0.2},
                                                    "text": "Logo blurry", "status": "open"}},
    }))
    out = todo(room, notes)
    assert "0:02.0–0:04.5 · Too slow" in out
    assert "0:06.0 [region x 10% y 25%, 50%×20%] · Logo blurry" in out


def test_region_of_clamps_and_rejects_bad_regions():
    assert region_of({"region": {"x": 0.8, "y": -0.1, "w": 0.5, "h": 0.3}}) == (0.8, 0.0, pytest.approx(0.2), 0.3)
    assert region_of({"region": {"x": 0.2, "y": 0.2, "w": 0, "h": 0.3}}) is None
    assert region_of({"region": {"x": "a"}}) is None and region_of({"region": None}) is None and region_of({}) is None
    assert where({"t": None, "tEnd": None}) == "whole" and where({"item": "01-hook", "t": 3}) == "01-hook"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_frames_cover_range_ends_and_box_regions(room_dir, tmp_path):
    video = room_dir / "media" / "poll.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x112:d=3:r=10",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    room = Room.load(room_dir)
    notes = load_export(export(tmp_path, {
        "pt": {"id": "pt", "version": 1, "data": {"cut": "poll", "t": 1, "text": "a", "status": "open"}},
        "rg": {"id": "rg", "version": 1, "data": {"cut": "poll", "t": 0.5, "tEnd": 2, "text": "b", "status": "open"}},
        "bx": {"id": "bx", "version": 1, "data": {"cut": "poll", "t": None, "region": {"x": 0, "y": 0, "w": 0.5, "h": 0.5},
                                                    "text": "c", "status": "open"}},
        "wh": {"id": "wh", "version": 1, "data": {"cut": "poll", "t": None, "text": "d", "status": "open"}},
    }))
    done = extract_frames(room, notes, width=64)
    names = sorted(p.name for _, p in done)
    assert names == ["poll_0000.00_bx.png", "poll_0000.50_rg_start.png", "poll_0001.00_pt.png", "poll_0002.00_rg_end.png"]
    box = next(p for _, p in done if p.name.startswith("poll_0000.00_bx"))
    plain = next(p for _, p in done if p.name.startswith("poll_0001.00_pt"))
    red = lambda p: subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", "crop=4:4:0:0,scale=1:1", "-f", "rawvideo",  # noqa: E731
                                    "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    assert red(box)[0] > 150 and red(plain)[0] < 40  # the box's corner is red, the plain frame stays black


def test_fix_writes_pin_the_note_and_name_the_cut_version(room_dir, tmp_path, capsys):
    uploaded(room_dir, capsys)
    room = Room.load(room_dir)
    stage(room, build_records(room, probe=NO_PROBE))
    confirm(room, parse_written('- set "cuts"/"poll" (version 1)'))
    room.state["records"]["cuts/poll"]["confirmed"]["version"] = 3
    save_notes(room, load_export(export(tmp_path, {"n1": {"id": "n1", "version": 7, "data": {"cut": "poll", "t": 2, "text": "x", "status": "open"}}})))
    w = fix_writes(room, {"n1": "Moved it."})
    assert w == [{"op": "update", "collection": "notes", "doc_id": "n1", "file_path": w[0]["file_path"], "if_version": 7}]
    assert json.loads(Path(w[0]["file_path"]).read_text()) == {"status": "fixed", "reply": "Moved it.", "fixedIn": 3}
    with pytest.raises(RoomError, match="not in the last export"):
        fix_writes(room, {"nope": "x"})


def test_fix_refuses_while_a_build_is_unwritten(room_dir, tmp_path, capsys):
    uploaded(room_dir, capsys)
    room = Room.load(room_dir)
    stage(room, build_records(room, probe=NO_PROBE))  # pending, never confirmed
    save_notes(room, load_export(export(tmp_path, {"n1": {"id": "n1", "version": 1, "data": {"cut": "poll", "t": 2, "text": "x", "status": "open"}}})))
    with pytest.raises(RoomError, match="not written yet"):
        fix_writes(room, {"n1": "Moved it."})


def test_written_records_new_note_versions(room_dir, tmp_path):
    room = Room.load(room_dir)
    save_notes(room, load_export(export(tmp_path, {"n1": {"id": "n1", "version": 2, "data": {"cut": "poll", "text": "x", "status": "open"}}})))
    confirm(room, parse_written('- update "notes"/"n1" (version 5)'))
    assert json.loads((room.state_dir / "notes.json").read_text())[0]["dbVersion"] == 5


def test_page_carries_the_room_title(room_dir, capsys):
    out = room_dir / "page.html"
    assert run(room_dir, "page", "-o", str(out)) == 0
    html = out.read_text()
    assert html.startswith("<title>Test room</title>")
    assert 'db.collection("notes")' in html and 'db.doc("room/meta")' in html
