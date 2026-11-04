"""Notes the owner left in a room: read an ArtifactData export, list them as a to-do, grab their frames, answer them.

Note text is the owner's data. The CLI prints it so a session can act on it; it never runs or evaluates it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .room import Room, RoomError, kind_of, load_json, set_items

STATUSES = ("open", "fixed", "resolved", "wontfix")


def fmt_t(t: float | None) -> str:
    if t is None:
        return "whole"
    m, s = divmod(float(t), 60)
    return f"{int(m)}:{s:04.1f}"


def region_of(note: dict) -> tuple[float, float, float, float] | None:
    """A note's frame region as (x, y, w, h), fractions of the frame clamped to it, or None."""
    r = note.get("region")
    if not isinstance(r, dict):
        return None
    try:
        x, y, w, h = (min(1.0, max(0.0, float(r[k]))) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    w, h = min(w, 1 - x), min(h, 1 - y)
    return (x, y, w, h) if w > 0 and h > 0 else None


def spoken(text: str) -> str:
    """A script line's spoken text: delivery cues ("[whisper]") taken out, white space collapsed.

    Notes on words keep character offsets (qStart, qEnd) into this string; the page computes it the same way.
    """
    return " ".join(re.sub(r"\[[^\]]*\]", " ", str(text or "")).split())


def quote_span(note: dict, line_text: str) -> tuple[int, int] | None:
    """Where a script note's words sit in the line's spoken text: its offsets while they still match the line,
    else the first place its quote occurs, else None (the line no longer has those words)."""
    sp, q = spoken(line_text), note.get("quote")
    q = q if isinstance(q, str) else ""
    a, b = note.get("qStart"), note.get("qEnd")
    if isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(sp) and (not q or sp[a:b] == q):
        return a, b
    at = sp.find(q) if q else -1
    return (at, at + len(q)) if at >= 0 else None


def marked_line(note: dict, line_text: str) -> str:
    """The line as the room has it now, with the note's words in «guillemets» (or noted as gone)."""
    sp = spoken(line_text)
    span = quote_span(note, line_text)
    if span:
        a, b = span
        return f"{sp[:a]}«{sp[a:b]}»{sp[b:]}"
    if isinstance(note.get("quote"), str) and note["quote"].strip():
        return f"{sp}  (the quoted words are no longer in this line)"
    return sp


def script_line(note: dict) -> int | None:
    """The 0-based script line a note is on, or None."""
    try:
        i = int(note["line"])
    except (KeyError, TypeError, ValueError):
        return None
    return i if i >= 0 else None


TAKE_TYPES = ("video/mp4", "video/webm")


def take_of(note: dict) -> dict | None:
    """A script note's voice take as {asset, seconds, type}, or None when it has none or it is malformed."""
    t = note.get("take")
    if script_line(note) is None or not isinstance(t, dict):
        return None
    asset, secs, typ = t.get("asset"), t.get("seconds"), t.get("type")
    if not isinstance(asset, str) or not re.fullmatch(r"[0-9a-f]{32}", asset):
        return None
    if isinstance(secs, bool) or not isinstance(secs, (int, float)) or secs < 0 or typ not in TAKE_TYPES:
        return None
    return {"asset": asset, "seconds": float(secs), "type": typ}


def where(note: dict) -> str:
    """Where a note points: set item, time range, time or whole cut, plus its frame region and script line."""
    if note.get("t") is not None and note.get("tEnd") is not None:
        at = f"{fmt_t(note['t'])}–{fmt_t(note['tEnd'])}"
    else:
        at = fmt_t(note.get("t"))
    if note.get("item"):   # a set item; a clip item may have a time or range too ("02-clip @ 0:01.0–0:02.5")
        at = note["item"] + (f" @ {at}" if note.get("t") is not None else "")
    r = region_of(note)
    if r:
        at += " [region x {:.0%} y {:.0%}, {:.0%}×{:.0%}]".format(*r)
    i = script_line(note)
    if i is not None:
        q = note.get("quote")
        at += f" [script line {i + 1}" + (f", on “{q}”" if isinstance(q, str) and q.strip() else "") + "]"
    return at


def _normalize(obj: dict, fallback_id: str) -> dict | None:
    """One exported document → a flat note with `id` and `dbVersion`.

    Accepts the raw document body, or a wrapper like `{"id": …, "data": {…}, "version": n}` (list/query output).
    """
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("data"), dict) and ("id" in obj or "version" in obj):
        body, nid, ver = obj["data"], str(obj.get("id") or fallback_id), obj.get("version")
    else:
        body, nid = obj, str(obj.get("id") or fallback_id)
        ver = obj.get("__version__") or obj.get("_version")
    if "text" not in body or "cut" not in body:
        return None
    note = {k: v for k, v in body.items() if not k.startswith("__")}
    note["id"] = nid
    note["dbVersion"] = int(ver) if ver is not None else None
    return note


def load_export(path: str | Path) -> list[dict]:
    """Every note in an export: a folder of JSON files (out_dir), one JSON file, or a JSON list."""
    p = Path(path)
    files = sorted(p.rglob("*.json")) if p.is_dir() else [p]
    notes = []
    for f in files:
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        items = data if isinstance(data, list) else (data.get("documents") or data.get("docs") or [data]) if isinstance(data, dict) else []
        for i, obj in enumerate(items):
            n = _normalize(obj, f.stem if len(items) == 1 else f"{f.stem}-{i}")
            if n:
                notes.append(n)
    return notes


def save_notes(room: Room, notes: list[dict]) -> None:
    room.state_dir.mkdir(exist_ok=True)
    (room.state_dir / "notes.json").write_text(json.dumps(notes, indent=1, ensure_ascii=False) + "\n")


def saved_notes(room: Room) -> list[dict]:
    p = room.state_dir / "notes.json"
    if not p.exists():
        raise RoomError("no notes saved yet (export them with ArtifactData and run `cut-review notes DIR`)")
    notes = load_json(p.read_text(), str(p))
    if not isinstance(notes, list):
        raise RoomError(f"{p} is not a JSON list of notes")
    return notes


def set_note_version(room: Room, note_id: str, version: int | None) -> bool:
    p = room.state_dir / "notes.json"
    if not p.exists() or version is None:
        return False
    notes = saved_notes(room)
    hit = False
    for n in notes:
        if n["id"] == note_id:
            n["dbVersion"] = version
            hit = True
    if hit:
        save_notes(room, notes)
    return hit


def todo(room: Room, notes: list[dict], show_all: bool = False) -> str:
    """A to-do list grouped by cut, in the room's order, timed notes first."""
    keys = [c["key"] for c in room.manifest.get("cuts", [])] + [s["key"] for s in room.manifest.get("sets", [])]
    titles = {e["key"]: e.get("title", e["key"]) for e in room.manifest.get("cuts", []) + room.manifest.get("sets", [])}
    scripts = {c["key"]: c.get("script") or [] for c in room.manifest.get("cuts", [])}
    counts = {s: sum(1 for n in notes if n.get("status") == s) for s in STATUSES}
    lines = [f"# Notes: {counts['open']} open, {counts['fixed']} fixed (waiting for the owner), "
             f"{counts['resolved']} resolved, {counts['wontfix']} won't fix", ""]
    order = {k: i for i, k in enumerate(keys)}
    shown = [n for n in notes if show_all or n.get("status") == "open"]
    for key in sorted({n["cut"] for n in shown}, key=lambda k: (order.get(k, 1e9), k)):
        mine = sorted((n for n in shown if n["cut"] == key), key=lambda n: (n.get("t") is None, n.get("t") or 0))
        ver = room.state["records"].get(f"cuts/{key}", room.state["records"].get(f"sets/{key}", {})).get("confirmed", {}).get("version")
        lines.append(f"## {key}: {titles.get(key, '(not in room.json)')}" + (f" (now v{ver})" if ver else ""))
        for n in mine:
            text = n["text"] or ("(no words: listen to the take)" if n.get("take") else "")
            lines.append(f"- [{n.get('status')}] {where(n)} · {text}  (id {n['id']}, written on v{n.get('version', 1)})")
            i, script = script_line(n), scripts.get(key, [])
            if i is not None and i < len(script):
                lines.append(f"  line: {marked_line(n, script[i].get('text', ''))}")
            take = take_of(n)
            if take:
                lines.append(f"  take: {take['seconds']:.1f} s (asset {take['asset'][:4]}…)")
            if n.get("reply"):
                lines.append(f"  reply: {n['reply']}")
        lines.append("")
    if not shown:
        lines.append("Nothing open.")
    return "\n".join(lines).rstrip() + "\n"


def _boxed(r: tuple[float, float, float, float] | None, width: int) -> str:
    """The ffmpeg filter that scales a frame to `width` with the region (if any) boxed in red."""
    vf = f"scale={width}:-2"
    return ("drawbox=x=iw*{}:y=ih*{}:w=iw*{}:h=ih*{}:color=red@0.9:t=6,".format(*r) + vf) if r else vf


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(name)).strip("-") or "item"


def _shots(n: dict) -> list[tuple[float, str]]:
    """The times to grab for a timed note: its frame, or the first and last frame of its range."""
    t = float(n.get("t") or 0)
    if n.get("tEnd") is not None and float(n["tEnd"]) > t:
        return [(t, "_start"), (float(n["tEnd"]), "_end")]
    return [(t, "")]


def _grab(video: Path, at: float, r, width: int, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(video),
                    "-frames:v", "1", "-vf", _boxed(r, width), str(dst)], check=True, timeout=60)


def _set_clip(room: Room, sets: dict[str, list[dict]], n: dict) -> tuple[Path | None, str]:
    """The local clip file behind a timed note on a set item, or None and why there is no frame to take."""
    item = n.get("item")
    if not item:
        return None, "a timed note on the whole set has no clip to take a frame from"
    it = next((x for x in sets[n["cut"]] if x["name"] == item), None)
    if it is None:
        return None, f"item {item} is not in set {n['cut']} in room.json"
    if kind_of(it["file"]) != "clip":
        return None, f"item {item} is a still, so a time on it has no frame"
    f = room.abspath(it["file"])
    if not f.is_file():
        return None, f"clip {it['file']} is not on disk"
    return f, ""


def extract_frames(room: Room, notes: list[dict], width: int = 540,
                   skipped: list[tuple[dict, str]] | None = None) -> list[tuple[dict, Path]]:
    """The frames behind every open note on a cut or on a set's clip, and the stills behind open set-item notes
    with a region, as PNGs in .cut-review/frames/. Needs ffmpeg.

    A timed note gives its frame; a range note gives its first and last frame; a note with a region has the region
    boxed in red (a whole-cut note with a region uses the first frame). A region on a set's still is boxed on that
    image (a set note without a region or a time gives nothing: the file is the item itself). A timed note on a
    set's clip item gives that clip's frame(s) when the clip is a local file in room.json; otherwise it is appended
    to `skipped` as (note, reason).
    """
    if not shutil.which("ffmpeg"):
        raise RoomError("ffmpeg is not on PATH")
    files = {c["key"]: room.abspath(c["file"]) for c in room.manifest.get("cuts", [])}
    sets = {s["key"]: set_items(room, s) for s in room.manifest.get("sets", [])}
    stills = {(k, it["name"]): room.abspath(it["file"]) for k, items in sets.items() for it in items if kind_of(it["file"]) == "still"}
    outdir = room.state_dir / "frames"
    outdir.mkdir(parents=True, exist_ok=True)
    done = []
    for n in notes:
        r = region_of(n)
        if n.get("status") != "open":
            continue
        if n["cut"] in sets:
            if n.get("item") and r and (n["cut"], n["item"]) in stills:
                dst = outdir / f"{n['cut']}_{_safe(n['item'])}_{n['id']}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(stills[n["cut"], n["item"]]),
                                "-frames:v", "1", "-vf", _boxed(r, width), str(dst)], check=True, timeout=60)
                done.append((n, dst))
                continue
            if n.get("t") is None:
                continue
            clip, why = _set_clip(room, sets, n)
            if clip is None:
                if skipped is not None:
                    skipped.append((n, why))
                continue
            for at, suffix in _shots(n):
                dst = outdir / f"{n['cut']}_{_safe(n['item'])}_{at:07.2f}_{n['id']}{suffix}.png"
                _grab(clip, at, r, width, dst)
                done.append((n, dst))
            continue
        if n["cut"] not in files or (n.get("t") is None and not r):
            continue
        for at, suffix in _shots(n):
            dst = outdir / f"{n['cut']}_{at:07.2f}_{n['id']}{suffix}.png"
            _grab(files[n["cut"]], at, r, width, dst)
            done.append((n, dst))
    return done


def fix_writes(room: Room, replies: dict[str, str], status: str = "fixed") -> list[dict]:
    """Update writes that answer notes: status, reply and the version the fix is in, pinned to each note's version."""
    if status not in ("fixed", "wontfix"):
        raise RoomError("status must be fixed or wontfix")
    notes = {n["id"]: n for n in saved_notes(room)}
    outdir = room.state_dir / "out"
    outdir.mkdir(parents=True, exist_ok=True)
    writes = []
    for nid, reply in replies.items():
        n = notes.get(nid)
        if not n:
            raise RoomError(f"note {nid} is not in the last export (run `cut-review notes DIR` again)")
        if not n.get("dbVersion"):
            raise RoomError(f"note {nid} has no database version in the export; re-export it with ArtifactData")
        key = n["cut"]
        rec = room.state["records"].get(f"cuts/{key}") or room.state["records"].get(f"sets/{key}") or {}
        conf = rec.get("confirmed", {})
        if status == "fixed" and rec.get("pending"):
            raise RoomError(f"{key} has a build that was not written yet: send its batch and run `cut-review written` first")
        data = {"status": status, "reply": reply}
        if status == "fixed":
            data["fixedIn"] = conf.get("version", 1)
        path = outdir / f"notes__{nid}.json"
        path.write_text(json.dumps(data, ensure_ascii=False) + "\n")
        writes.append({"op": "update", "collection": "notes", "doc_id": nid, "file_path": str(path), "if_version": n["dbVersion"]})
    return writes
