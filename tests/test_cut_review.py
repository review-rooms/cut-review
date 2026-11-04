import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cut_review import cli
from cut_review.notes import extract_frames, fix_writes, load_export, marked_line, quote_span, region_of, save_notes, spoken, take_of, todo, where
from cut_review.parse import parse_assets, parse_listed_versions, parse_written
from cut_review.records import build_records, chunks, confirm, stage
from cut_review.room import Room, RoomError
from cut_review.takes import take_row

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


def test_alternate_videos_are_uploaded_built_and_versioned(room_dir, capsys):
    media = room_dir / "media"
    (media / "poll.vo.mp4").write_bytes(b"with-voice")
    m = json.loads((room_dir / "room.json").read_text())
    m["cuts"][0]["alts"] = [{"key": "vo", "label": "Voice + music", "file": "poll.vo.mp4"}]
    m["cuts"][0]["videoLabel"] = "Silent"
    m["cuts"][0]["altDefault"] = "vo"
    (room_dir / "room.json").write_text(json.dumps(m))
    assert "poll.vo.mp4" in Room.load(room_dir).referenced_files()
    with pytest.raises(RoomError, match="poll.vo.mp4"):
        uploaded(room_dir, capsys)
        build_records(Room.load(room_dir), probe=NO_PROBE)
    (room_dir / "up2.txt").write_text(upload_text(room_dir, {"poll.vo.mp4": "f" * 32}))
    assert run(room_dir, "assets", str(room_dir / "up2.txt")) == 0
    recs = {f"{c}/{d}": data for c, d, data, _ in build_records(Room.load(room_dir), probe=NO_PROBE)}
    poll = recs["cuts/poll"]
    assert poll["alts"] == [{"key": "vo", "label": "Voice + music", "video": "/_blob/" + "f" * 32}]
    assert poll["videoLabel"] == "Silent" and poll["altDefault"] == "vo"
    assert "alts" not in recs["sets/carousel"]


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


def test_todo_shows_script_lines_and_quotes(room_dir, tmp_path):
    room = Room.load(room_dir)
    notes = load_export(export(tmp_path, {
        "q": {"id": "q", "version": 1, "data": {"cut": "poll", "t": 0, "tEnd": 3, "line": 0, "quote": "Hook",
                                                  "text": "Say it slower", "status": "open"}},
        "l": {"id": "l", "version": 1, "data": {"cut": "poll", "t": 0, "tEnd": 3, "line": 0, "quote": None,
                                                  "text": "Cut this line", "status": "open"}},
        "x": {"id": "x", "version": 1, "data": {"cut": "poll", "t": 0, "line": 7, "text": "Line gone", "status": "open"}},
    }))
    out = todo(room, notes)
    assert '0:00.0–0:03.0 [script line 1, on “Hook”] · Say it slower' in out
    assert '0:00.0–0:03.0 [script line 1] · Cut this line' in out
    assert '  line: Hook' in out                       # the line as the room has it now, so a session sees what it said
    assert '[script line 8] · Line gone' in out          # a line the script no longer has still shows its number


A = "39bb1bc8def01eca67a6f983358b3c0d"


def test_take_of_accepts_only_well_formed_takes_on_script_lines():
    ok = {"line": 0, "take": {"asset": A, "seconds": 4.2, "type": "video/mp4"}}
    assert take_of(ok) == {"asset": A, "seconds": 4.2, "type": "video/mp4"}
    for bad in ({"asset": "xyz", "seconds": 1, "type": "video/mp4"}, {"asset": A, "seconds": "4", "type": "video/mp4"},
                {"asset": A, "seconds": True, "type": "video/mp4"}, {"asset": A, "seconds": -1, "type": "video/mp4"},
                {"asset": A, "seconds": 1, "type": "audio/mp4"}, {"seconds": 1, "type": "video/mp4"}, "take", None):
        assert take_of({"line": 0, "take": bad}) is None
    assert take_of({"line": None, "take": ok["take"]}) is None


def test_todo_shows_a_take_under_its_line(room_dir, tmp_path):
    room = Room.load(room_dir)
    notes = load_export(export(tmp_path, {
        "t": {"id": "t", "version": 1, "data": {"cut": "poll", "t": 0, "line": 0, "text": "Like this", "status": "open",
                                                  "take": {"asset": A, "seconds": 4.2, "type": "video/mp4"}}},
        "b": {"id": "b", "version": 1, "data": {"cut": "poll", "t": 1, "line": 0, "text": "Broken", "status": "open",
                                                  "take": {"asset": "nope"}}},
    }))
    out = todo(room, notes)
    assert "Like this  (id t, written on v1)\n  line: Hook\n  take: 4.2 s (asset 39bb…)" in out
    assert out.count("take:") == 1


def test_page_script_scroll_respects_reduced_motion(room_dir, capsys):
    out = room_dir / "page.html"
    run(room_dir, "page", "-o", str(out))
    html = out.read_text()
    assert 'behavior: "smooth"' not in html and "prefers-reduced-motion: reduce)\").matches" in html


def test_spoken_drops_cues_and_collapses_space():
    assert spoken("  [whisper] B,  by the [pause] exhaust.\n0 of 6. ") == "B, by the exhaust. 0 of 6."
    assert spoken("wo[x]rd") == "wo rd"   # a cue inside a word splits it, on the page too


def test_word_notes_mark_the_exact_words_even_when_repeated():
    line = "[calm] 0 of 6 here, then 0 of 6 there."
    sp = spoken(line)                     # "0 of 6 here, then 0 of 6 there."
    second = sp.index("0 of 6", 1)
    note = {"line": 0, "quote": "0 of 6", "qStart": second, "qEnd": second + 6}
    assert quote_span(note, line) == (second, second + 6)
    assert marked_line(note, line) == "0 of 6 here, then «0 of 6» there."
    # a single character is a span too
    assert marked_line({"line": 0, "quote": "6", "qStart": 5, "qEnd": 6}, line) == "0 of «6» here, then 0 of 6 there."


def test_word_notes_survive_a_rewritten_line_or_say_the_words_are_gone():
    note = {"line": 0, "quote": "exhaust", "qStart": 30, "qEnd": 37}          # offsets from an older wording
    assert marked_line(note, "B, by the exhaust.") == "B, by the «exhaust»."      # falls back to the quote
    assert marked_line(note, "B, by the vent.") == "B, by the vent.  (the quoted words are no longer in this line)"
    assert marked_line({"line": 0, "quote": None}, "[soft] Whole line.") == "Whole line."


def test_todo_prints_the_line_with_the_words_marked(room_dir, tmp_path):
    room = Room.load(room_dir)
    notes = load_export(export(tmp_path, {
        "w": {"id": "w", "version": 1, "data": {"cut": "poll", "t": 0, "tEnd": 3, "line": 0, "quote": "Hoo",
                                                  "qStart": 0, "qEnd": 3, "text": "Hard H", "status": "open"}},
    }))
    out = todo(room, notes)
    assert '[script line 1, on “Hoo”] · Hard H' in out and "  line: «Hoo»k" in out


def test_page_and_cli_agree_on_the_spoken_text(room_dir, capsys):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = room_dir / "page.html"
    run(room_dir, "page", "-o", str(out))
    html = out.read_text()
    fn = next(l for l in html.splitlines() if "const spokenOf" in l).strip()
    samples = ["  [whisper] B,  by the [pause] exhaust.\n0 of 6. ", "wo[x]rd", "[only a cue]", "Plain line", "a\u00a0b  [x]c"]
    js = fn + "\nconsole.log(JSON.stringify(" + json.dumps(samples) + ".map(spokenOf)));"
    got = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert got == [spoken(x) for x in samples]


def test_page_stores_word_offsets_and_offers_word_taps(room_dir, capsys):
    out = room_dir / "page.html"
    run(room_dir, "page", "-o", str(out))
    html = out.read_text()
    assert "qStart:" in html and "qEnd:" in html            # the note keeps where its words are
    assert 'addEventListener("selectionchange"' in html     # a selection gets the floating Comment button
    assert "wordTap(i, w, ev.shiftKey)" in html               # tapping a word comments on it
    assert "innerHTML" not in html                           # script text and quotes only ever go in as text


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


def test_page_asks_to_publish_with_downloads(room_dir, capsys):
    # Pages on claude.ai can't download by themselves: the Download button goes through `downloads`,
    # so an unlinked room must be told to publish with it.
    out = room_dir / "page.html"
    assert run(room_dir, "page", "-o", str(out)) == 0
    assert '"downloads": true' in capsys.readouterr().err
    assert 'use("downloads")' in out.read_text()


# ---------------------------------------------------------------- voice takes
B = "0f" * 16
URL = "https://claude.ai/artifact/room1"


def take_note(nid, status="open", asset=A, line=0, **more):
    data = {"cut": "poll", "t": 0, "tEnd": 3, "line": line, "text": f"note {nid}", "status": status,
            "take": {"asset": asset, "seconds": 4.2, "type": "video/mp4"} if asset else None, **more}
    return {"id": nid, "version": 1, "data": data}


def save_takes(room_dir, tmp_path, *docs, link=True):
    if link:
        assert run(room_dir, "link", URL) == 0
    save_notes(Room.load(room_dir), load_export(export(tmp_path, {d["id"]: d for d in docs})))


def test_takes_prints_a_read_call_per_open_take(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("o"), take_note("r", status="resolved", asset=B), take_note("n", asset=None))
    capsys.readouterr()
    assert run(room_dir, "takes") == 0
    out = capsys.readouterr().out
    calls = json.loads(out[out.index("["):])
    assert calls == [{"action": "read", "url": URL, "path": A, "out_dir": str(room_dir / ".cut-review" / "takes" / "raw")}]
    assert "then run `cut-review takes` again" in out


def test_takes_with_none_open_says_so(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("r", status="fixed"))
    capsys.readouterr()
    assert run(room_dir, "takes") == 0
    assert capsys.readouterr().out.strip() == "No open notes with a take."


def test_takes_refuses_without_a_linked_room(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("o"), link=False)
    assert run(room_dir, "takes") == 1
    assert "cut-review link" in capsys.readouterr().err


def test_take_row_words_for_spans_gone_words_and_gone_lines(room_dir):
    room = Room.load(room_dir)
    base = {"id": "x", "cut": "poll", "text": "Like this", "line": 0}
    row = take_row(room, {**base, "quote": "Hook", "qStart": 0, "qEnd": 4})
    assert row == {"note": "x", "cut": "poll", "line": 0, "from": 0, "to": 3, "text": "Hook", "words": "Hook", "noteText": "Like this"}
    assert take_row(room, {**base, "quote": "Gone"})["words"] == "Gone"
    assert take_row(room, {**base, "quote": None})["words"] == "Hook"
    gone = take_row(room, {**base, "line": 5, "quote": "Hook"})
    assert (gone["text"], gone["from"], gone["to"], gone["words"]) == ("", None, None, "Hook")


def raw_take(room_dir, asset=A):
    d = room_dir / ".cut-review" / "takes" / "raw"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"{asset}.mp4"   # a quiet 3 s tone after 1 s of silence, 48 kHz stereo AAC, like a phone take
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
                    "-af", "volume=0.05,adelay=1000|1000", "-ac", "2", "-c:a", "aac", str(dst)], check=True)
    return dst


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return j["streams"][0], float(j["format"]["duration"])


needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is not installed")


@needs_ffmpeg
def test_takes_converts_downloads_to_24k_mono_wav_and_lists_them(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("o", quote="Hook", qStart=0, qEnd=4))
    raw_take(room_dir)
    capsys.readouterr()
    assert run(room_dir, "takes") == 0
    out = capsys.readouterr().out
    wav = room_dir / ".cut-review" / "takes" / "poll_line1_o.wav"
    stream, secs = probe(wav)
    assert (stream["codec_name"], stream["sample_rate"], stream["channels"]) == ("pcm_s16le", "24000", 1)
    assert 2.5 < secs < 3.6                       # the leading second of silence is gone
    rows = json.loads((wav.parent / "takes.json").read_text())
    assert rows == [{"note": "o", "cut": "poll", "line": 0, "from": 0, "to": 3, "text": "Hook", "words": "Hook",
                     "wav": "poll_line1_o.wav", "seconds": rows[0]["seconds"], "noteText": "note o"}]
    assert abs(rows[0]["seconds"] - secs) < 0.11
    assert f"{wav}  ← poll line 1: Hook" in out and '"action": "read"' not in out


@needs_ffmpeg
def test_takes_out_dir_and_mixed_downloaded_and_missing(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("o"), take_note("m", asset=B))
    raw_take(room_dir)
    capsys.readouterr()
    assert run(room_dir, "takes", "--out", str(tmp_path / "x")) == 0
    out = capsys.readouterr().out
    assert [r["note"] for r in json.loads((tmp_path / "x" / "takes.json").read_text())] == ["o"]
    assert (tmp_path / "x" / "poll_line1_o.wav").is_file()
    assert json.loads(out[out.index("["):])[0]["path"] == B


def page_html(room_dir) -> str:
    out = room_dir / "page.html"
    assert run(room_dir, "page", "-o", str(out)) == 0
    return out.read_text()


def test_page_records_takes_live_with_no_file_upload(room_dir, capsys):
    html = page_html(room_dir)
    assert 'type="file"' not in html and "<script src=" not in html     # no picker, no camera, no mp4 parsing
    assert "getUserMedia({ audio: true })" in html and "new MediaRecorder(" in html
    assert 'allowsFeature("microphone")' in html                         # the button shows only where the mic is usable
    assert "innerHTML" not in html and html.startswith("<title>")


def test_page_offers_takes_only_in_the_note_form(room_dir, capsys):
    html = page_html(room_dir)
    assert html.count("🎙 Record how it should sound") == 1 and "Pick a file" not in html
    assert 'id="takeRow" hidden' in html and 'id="b-rec"' in html and 'id="b-stop"' in html
    assert "take: S.line && take && asset" in html and 'use("assets")' in html


@needs_ffmpeg
def test_takes_names_stay_inside_the_out_dir(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("../evil"), take_note("x2", asset=B, cut="../../outside"))
    raw_take(room_dir); raw_take(room_dir, B)
    capsys.readouterr()
    run(room_dir, "takes")
    out_dir = room_dir / ".cut-review" / "takes"
    wavs = sorted(p.name for p in out_dir.glob("*.wav"))
    assert wavs == ["poll_line1____evil.wav"]                 # a cut the room doesn't have is skipped
    assert not list(room_dir.parent.rglob("outside*")) and not (room_dir / ".cut-review" / "evil.wav").exists()


@needs_ffmpeg
def test_takes_keeps_going_past_a_bad_download(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("bad", asset=B), take_note("good"))
    raw_take(room_dir)
    (room_dir / ".cut-review" / "takes" / "raw" / f"{B}.mp4").write_bytes(b"not a video")
    capsys.readouterr()
    assert run(room_dir, "takes") == 1
    io = capsys.readouterr()
    assert [r["note"] for r in json.loads((room_dir / ".cut-review" / "takes" / "takes.json").read_text())] == ["good"]
    assert "couldn't convert" in io.err and B in io.err


def test_takes_folders_keep_themselves_out_of_git(room_dir, tmp_path, capsys):
    save_takes(room_dir, tmp_path, take_note("o"))
    assert run(room_dir, "takes", "--out", str(tmp_path / "x")) == 0
    for d in (room_dir / ".cut-review" / "takes" / "raw", tmp_path / "x"):
        assert (d / ".gitignore").read_text() == "*\n"


# ---------------------------------------------------------------- page performance and UX

def test_page_follows_playback_per_frame_with_transforms(room_dir, capsys):
    html = page_html(room_dir)
    assert "vid.requestVideoFrameCallback(onFrame)" in html          # not timeupdate's ~4 steps a second
    paint = html[html.index("function paint(t)"):html.index("let looping")]
    assert 'style.transform = "scaleX(' in paint and 'style.transform = "translateX(' in paint
    assert ".left =" not in paint and "getBoundingClientRect" not in paint and ".textContent =" not in paint


def test_page_drops_unchanged_snapshots_and_keeps_cards(room_dir, capsys):
    html = page_html(room_dir)
    for c in ("meta", "cuts", "sets", "notes", "verdicts"):
        assert f'changed("{c}", ' in html                         # an unchanged snapshot renders nothing
    assert "requestAnimationFrame(go)" in html                      # a burst of snapshots renders once
    assert "x.sig !== sig" in html and "noteCards.set(" in html     # note cards reused while their note is unchanged
    assert "if (sig !== itemsSig)" in html                          # set clips aren't rebuilt by a note (issue 11)


def test_page_drags_apply_once_per_frame(room_dir, capsys):
    html = page_html(room_dir)
    assert "const scrubSoon = perFrame(" in html and "const draftSoon = perFrame(renderDraft)" in html


def test_page_touch_targets_and_contract(room_dir, capsys):
    html = page_html(room_dir)
    assert "@media (pointer: coarse), (max-width: 760px) {\n  :root { --hit: 44px; }" in html and ".note button.t, .note .acts .btn { min-height: var(--hit); }" in html   # issue 10
    assert "padding-left: max(16px, env(safe-area-inset-left, 0px))" in html
    assert "padding-right: max(16px, env(safe-area-inset-right, 0px))" in html
    assert ':root[data-theme="dark"]' in html and ':root:not([data-theme="light"])' in html
    assert "innerHTML" not in html


def test_page_waits_for_sets_and_corrects_unknown_hashes(room_dir, capsys):
    html = page_html(room_dir)
    assert "if (!S.loaded.cuts || !S.loaded.sets) return;" in html   # issue 4: a set's hash on a cold load
    assert "if (want && !entryOf(want)) unknownKey(want);" in html     # issue 9
    assert 'history.replaceState(null, "", "#" + S.sel)' in html


def test_page_set_items_pick_and_whole_set(room_dir, capsys):
    html = page_html(room_dir)
    assert 'el("option", null, "Whole set")' in html and 'whole.value = ""' in html   # issue 6
    assert "card.onclick = " in html and '"ArrowRight"' in html


def test_page_flags_bad_times_and_spaces_cues(room_dir, capsys):
    html = page_html(room_dir)
    assert "&& !badTime();" in html and "isn't a time" in html                        # issue 7
    assert '{ if (out.length) out.push(document.createTextNode(" ")); out.push(el("span", "cue"' in html   # issue 8
    assert "write a few words and add the note" in html                                # issue 12
    assert "?? (S.line && S.line.i === i && S.line.qs != null ? S.line : null)" in html  # issue 5
