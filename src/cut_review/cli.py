"""cut-review: run a review room for rendered videos on claude.ai from a Claude session.

Uploading to a room and writing its database only work through Claude's own tools (Artifact, ArtifactData), so
this CLI prepares their inputs and reads their results. Every command works on the room project in the current
folder (or `-C DIR`): `room.json` plus the CLI's state in `.cut-review/`.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .notes import extract_frames, fix_writes, load_export, save_notes, saved_notes, todo, where
from .parse import parse_assets, parse_listed_versions, parse_written
from .records import build_records, chunks, confirm, stage
from .room import MANIFEST, MEDIA_EXT, VIDEO_EXT, Room, RoomError, sha256

UPLOAD_BATCH = 25          # Artifact asset upload: at most 25 files per call
UPLOAD_MAX_BYTES = 15 << 20  # and at most 15 MB per binary file


def _read(src: str) -> str:
    return sys.stdin.read() if src == "-" else Path(src).read_text()


def _print_batches(writes: list[dict], what: str) -> None:
    if not writes:
        print(f"Nothing to write: {what} already match the room.")
        return
    parts = chunks(writes)
    print(f"{len(writes)} write(s) for ArtifactData action \"batch\" ({len(parts)} call(s)); pass each list as `writes`:")
    for i, part in enumerate(parts, 1):
        print(f"\n# batch {i} of {len(parts)}")
        print(json.dumps(part, indent=1))
    print("\nThen save the tool's result to a file and run `cut-review written FILE`.")


# ---------------------------------------------------------------- commands
def cmd_init(a) -> int:
    d = Path(a.room).resolve()
    d.mkdir(parents=True, exist_ok=True)
    if (d / MANIFEST).exists() and not a.force:
        raise RoomError(f"{d / MANIFEST} exists (use --force to overwrite)")
    media = Path(a.media).expanduser() if a.media else Path(".")
    root = media if media.is_absolute() else (d / media)
    root = root.resolve()
    if not root.is_dir():
        raise RoomError(f"media folder {root} does not exist")
    files = sorted(p for p in root.iterdir() if p.is_file() and not p.name.startswith("."))
    names = {p.name for p in files}
    cuts = []
    for p in files:
        if p.suffix.lower() not in VIDEO_EXT:
            continue
        poster = next((n for n in (f"{p.stem}.poster.png", f"{p.stem}.poster.jpg", f"{p.stem}.png", f"{p.stem}.jpg") if n in names), None)
        c = {"key": _key(p.stem), "file": p.name, "title": p.stem.replace("-", " ").replace("_", " ").capitalize(),
             "group": "cuts", "aspect": "9:16", "tags": [], "description": "", "script": []}
        if poster:
            c["poster"] = poster
        cuts.append(c)
    sets = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if any(q.suffix.lower() in MEDIA_EXT for q in sub.iterdir()):
            sets.append({"key": _key(sub.name), "dir": sub.name, "title": sub.name.capitalize(), "group": "sets",
                         "aspect": "4:5", "description": ""})
    groups = [{"id": "cuts", "label": "Cuts"}] + ([{"id": "sets", "label": "Sets"}] if sets else [])
    manifest = {"title": a.title or d.name, "subtitle": "", "scriptLabel": "Script",
                "media": a.media or ".", "groups": groups, "cuts": cuts, "sets": sets}
    (d / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote {d / MANIFEST}: {len(cuts)} cut(s), {len(sets)} set(s) from {root}.")
    print("Edit titles, groups, aspects, tags and scripts there, then run `cut-review page`.")
    return 0


def _key(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-." else "-" for ch in s).strip("-.") or "cut"


# What the published page needs from the artifact viewer. `downloads` lets the Download button save a video
# (claude.ai pages can't download by themselves).
CAPABILITIES = '{"db": {}, "user": {}, "assets": {}, "downloads": true}'


def cmd_page(a) -> int:
    room = Room.load(a.room)
    page = resources.files("cut_review").joinpath("page/review-room.html").read_text()
    title = html.escape(room.manifest.get("title") or "Cut Review Room")
    page = page.replace("<title>Cut Review Room</title>", f"<title>{title}</title>", 1)
    out = Path(a.output) if a.output else room.state_dir / "review-room.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(out.resolve())
    if not room.state.get("artifact"):
        print(f'Publish it with the Artifact tool: file_path above, icon "video", '
              f'capabilities {CAPABILITIES}; then run `cut-review link URL`.', file=sys.stderr)
    return 0


def cmd_link(a) -> int:
    room = Room.load(a.room)
    if not a.url.startswith("https://claude.ai/"):
        raise RoomError("expected a claude.ai artifact URL")
    room.state["artifact"] = a.url.split("#")[0]
    room.save()
    print(f"Linked {room.state['artifact']}")
    return 0


def pending_uploads(room: Room) -> list[tuple[str, Path, int]]:
    out = []
    for rel in room.referenced_files():
        p = room.abspath(rel)
        if not p.is_file():
            raise RoomError(f"missing file: {p}")
        rec = room.state["files"].get(rel)
        if not rec or not rec.get("id") or rec.get("sha256") != sha256(p):
            out.append((rel, p, p.stat().st_size))
    return out


def cmd_uploads(a) -> int:
    room = Room.load(a.room)
    todo_ = pending_uploads(room)
    big = [rel for rel, _, size in todo_ if size > UPLOAD_MAX_BYTES]
    if big:
        raise RoomError("over the 15 MB upload limit (re-encode them smaller): " + ", ".join(big))
    batches = [[str(p) for _, p, _ in todo_[i:i + UPLOAD_BATCH]] for i in range(0, len(todo_), UPLOAD_BATCH)]
    if a.json:
        print(json.dumps({"artifact": room.state.get("artifact"), "batches": batches}))
        return 0
    if not batches:
        print("Nothing to upload: every file matches its last upload.")
        return 0
    print(f"{len(todo_)} file(s) to upload to {room.state.get('artifact') or '(no room linked yet)'} "
          f"in {len(batches)} call(s) of the Artifact tool with url, asset: true and file_paths:")
    for i, b in enumerate(batches, 1):
        print(f"\n# call {i} of {len(batches)}")
        print(json.dumps(b, indent=1))
    print("\nThen save each result to a file and run `cut-review assets FILE`.")
    return 0


def cmd_assets(a) -> int:
    room = Room.load(a.room)
    found = parse_assets(_read(a.source))
    if not found:
        raise RoomError("no uploaded files found in that text")
    known, unknown = 0, []
    for path, aid in found.items():
        rel = room.relpath(path)
        if rel is None or rel not in room.referenced_files():
            unknown.append(path)
            continue
        room.state["files"][rel] = {"id": aid, "sha256": sha256(room.abspath(rel))}
        known += 1
    room.save()
    print(f"Recorded {known} asset id(s).")
    if unknown:
        print("Not part of this room (ignored): " + ", ".join(unknown))
    left = len(pending_uploads(room))
    print(f"{left} file(s) still to upload." if left else "Every file is uploaded. Next: `cut-review build`.")
    return 0


def cmd_build(a) -> int:
    room = Room.load(a.room)
    notes = {}
    for n in a.note or []:
        key, sep, text = n.partition("=")
        if not sep or not text.strip():
            raise RoomError(f"--note needs KEY=TEXT, got {n!r}")
        notes[key] = text.strip()
    keys = {e["key"] for e in room.manifest.get("cuts", []) + room.manifest.get("sets", [])}
    unknown = sorted(set(notes) - keys)
    if unknown:
        raise RoomError("--note for keys not in room.json: " + ", ".join(unknown))
    records = build_records(room, notes)
    writes = stage(room, records, only_changed=not a.all)
    room.save()
    for coll, doc, data, _ in records:
        if coll in ("cuts", "sets"):
            pend = room.state["records"][f"{coll}/{doc}"].get("pending")
            if pend:
                print(f"{coll}/{doc}: v{data['version']}" + (f" ({data['changes'][-1]['note']})" if data["changes"] and data["changes"][-1]["v"] == data["version"] else ""))
    if not room.state.get("artifact"):
        print("Note: no room linked yet (`cut-review link URL`).", file=sys.stderr)
    _print_batches(writes, "all records")
    return 0


def cmd_written(a) -> int:
    room = Room.load(a.room)
    w = parse_written(_read(a.source))
    if not w:
        raise RoomError("no written documents found in that text")
    done = confirm(room, w)
    room.save()
    print(f"Recorded {len(done)} write(s): " + ", ".join(done))
    return 0


def cmd_notes(a) -> int:
    room = Room.load(a.room)
    notes = load_export(a.export)
    if not notes:
        raise RoomError(f"no notes found in {a.export}")
    if a.result:
        versions = parse_listed_versions(_read(a.result))
        for n in notes:
            if n["id"] in versions:
                n["dbVersion"] = versions[n["id"]]
    save_notes(room, notes)
    print(todo(room, notes, show_all=a.all), end="")
    missing = [n["id"] for n in notes if not n.get("dbVersion")]
    if missing:
        print(f"\nWarning: {len(missing)} note(s) have no database version, which `fix` needs. Save the ArtifactData "
              "list result (it names each document's version) and pass it with --result FILE.", file=sys.stderr)
    return 0


def cmd_frames(a) -> int:
    room = Room.load(a.room)
    done = extract_frames(room, saved_notes(room), a.width)
    if not done:
        print("No open timed or region notes.")
    for n, p in done:
        print(f"{p}  ← {n['cut']} {where(n)}: {n['text'][:80]}")
    return 0


def cmd_fix(a) -> int:
    room = Room.load(a.room)
    replies: dict[str, str] = {}
    if a.source:
        data = json.loads(_read(a.source))
        replies = {x["id"]: x["reply"] for x in data} if isinstance(data, list) else {str(k): str(v) for k, v in data.items()}
    for pair in a.pairs or []:
        nid, sep, reply = pair.partition("=")
        if not sep or not reply.strip():
            raise RoomError(f"expected ID=REPLY, got {pair!r}")
        replies[nid] = reply.strip()
    if not replies:
        raise RoomError("give ID=REPLY pairs or --from FILE")
    _print_batches(fix_writes(room, replies, a.status), "notes")
    return 0


def cmd_status(a) -> int:
    room = Room.load(a.room)
    print(f"Room:    {room.manifest.get('title')}  ({room.dir})")
    print(f"Artifact: {room.state.get('artifact') or '(not linked)'}")
    print(f"Media:   {room.media_root}")
    try:
        pend = pending_uploads(room)
    except RoomError as e:
        print(f"Uploads: {e}")
        pend = []
    print(f"Uploads: {len(pend)} pending" + (": " + ", ".join(r for r, _, _ in pend) if pend else ""))
    for kind in ("cuts", "sets"):
        for e in room.manifest.get(kind, []):
            rec = room.state["records"].get(f"{kind}/{e['key']}", {})
            conf, pend_ = rec.get("confirmed"), rec.get("pending")
            line = f"  {kind[:-1]:3s} {e['key']:16s} " + (f"v{conf['version']} in the room" if conf else "not in the room yet")
            if pend_:
                line += f", build v{pend_.get('version')} waiting to be written"
            print(line)
    p = room.state_dir / "notes.json"
    if p.exists():
        notes = json.loads(p.read_text())
        print(f"Notes (last export): {sum(n.get('status') == 'open' for n in notes)} open of {len(notes)}")
    return 0


# ---------------------------------------------------------------- main
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cut-review", description=__doc__.split("\n\n")[0])
    p.add_argument("-C", "--room", default=".", help="room project folder (default: current folder)")
    p.add_argument("--version", action="version", version=f"cut-review {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write a room.json listing the videos in a folder")
    s.add_argument("--media", help="folder with the videos, relative to the room folder or absolute (default: the room folder)")
    s.add_argument("--title")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("page", help="write the review page, ready to publish")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_page)

    s = sub.add_parser("link", help="record the published room's URL")
    s.add_argument("url")
    s.set_defaults(fn=cmd_link)

    s = sub.add_parser("uploads", help="list files to upload, in batches of 25")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_uploads)

    s = sub.add_parser("assets", help="record asset ids from an upload result (FILE or -)")
    s.add_argument("source")
    s.set_defaults(fn=cmd_assets)

    s = sub.add_parser("build", help="write the room's records and print the batch writes")
    s.add_argument("--note", action="append", metavar="KEY=TEXT", help="change-log line for a cut whose video changed")
    s.add_argument("--all", action="store_true", help="include records that did not change")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("written", help="record database versions from an ArtifactData result (FILE or -)")
    s.add_argument("source")
    s.set_defaults(fn=cmd_written)

    s = sub.add_parser("notes", help="read exported notes and print the to-do list")
    s.add_argument("export", help="the out_dir of an ArtifactData list/query of `notes`, or a JSON file")
    s.add_argument("--result", help="the saved ArtifactData list/query result text (FILE or -): gives each note's database version")
    s.add_argument("--all", action="store_true", help="also list fixed, resolved and won't-fix notes")
    s.set_defaults(fn=cmd_notes)

    s = sub.add_parser("frames", help="extract the frames behind every open timed, range or region note, and set stills with a region (ffmpeg)")
    s.add_argument("--width", type=int, default=540)
    s.set_defaults(fn=cmd_frames)

    s = sub.add_parser("fix", help="print the writes that answer notes")
    s.add_argument("pairs", nargs="*", metavar="ID=REPLY")
    s.add_argument("--from", dest="source", help="JSON file: {id: reply} or [{id, reply}]")
    s.add_argument("--status", default="fixed", choices=["fixed", "wontfix"])
    s.set_defaults(fn=cmd_fix)

    s = sub.add_parser("status", help="what is uploaded, built and written")
    s.set_defaults(fn=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except RoomError as e:
        print(f"cut-review: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
