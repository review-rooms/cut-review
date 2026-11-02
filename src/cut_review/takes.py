"""Voice takes: the owner's recordings of how a script line should sound, attached to notes in the room.

A take is the owner's voice. The CLI only lists, downloads (through Claude's Artifact tool) and converts it, as a
reference for re-generating that one line; it never sends it anywhere.
"""
from __future__ import annotations

from pathlib import Path

from .notes import quote_span, script_line, spoken, take_of
from .room import Room, RoomError

RAW = "takes/raw"   # under .cut-review/: where the Artifact reads save the downloaded takes


def open_takes(notes: list[dict]) -> list[tuple[dict, dict]]:
    """(note, take) for every open note with a well-formed take."""
    return [(n, t) for n in notes if n.get("status") == "open" and (t := take_of(n))]


def take_row(room: Room, note: dict) -> dict:
    """What a take is of: the script line's times and spoken text, and the words the note is on.

    `words` is the note's span of the line while it is still there, else its quote (what the owner said), else the
    whole line.
    """
    i = script_line(note)
    script = next((c.get("script") or [] for c in room.manifest.get("cuts", []) if c["key"] == note["cut"]), [])
    line = script[i] if i is not None and i < len(script) else None
    text = spoken(line.get("text", "")) if line else ""
    span = quote_span(note, line.get("text", "")) if line else None
    quote = note.get("quote") if isinstance(note.get("quote"), str) and note["quote"].strip() else None
    words = text[span[0]:span[1]] if span else quote or text
    return {"note": note["id"], "cut": note["cut"], "line": i, "from": line.get("from") if line else None,
            "to": line.get("to") if line else None, "text": text, "words": words, "noteText": note.get("text", "")}


def raw_file(room: Room, take: dict) -> Path | None:
    """The downloaded file of a take (saved by the Artifact read as <asset id>.<ext>), or None."""
    d = room.state_dir / RAW
    return next((p for p in sorted(d.glob(take["asset"] + ".*")) if p.is_file()), None) if d.is_dir() else None


def read_call(room: Room, take: dict) -> dict:
    """The Artifact tool call that downloads a take."""
    url = room.state.get("artifact")
    if not url:
        raise RoomError("no room linked (run `cut-review link URL`)")
    return {"action": "read", "url": url, "path": take["asset"], "out_dir": str(room.state_dir / RAW)}
