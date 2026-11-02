"""Voice takes: the owner's recordings of how a script line should sound, attached to notes in the room.

A take is the owner's voice. The CLI only lists, downloads (through Claude's Artifact tool) and converts it, as a
reference for re-generating that one line; it never sends it anywhere.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .notes import quote_span, script_line, spoken, take_of
from .records import probe_length
from .room import Room, RoomError

RAW = "takes/raw"   # under .cut-review/: where the Artifact reads save the downloaded takes
TRIM = "silenceremove=start_periods=1:start_threshold=-50dB"
FILTER = f"{TRIM},areverse,{TRIM},areverse,loudnorm=I=-20"   # silence off both ends, loudness evened out


def open_takes(notes: list[dict], cuts: set[str] | None = None) -> list[tuple[dict, dict]]:
    """(note, take) for every open note with a well-formed take (on one of `cuts`, when given)."""
    return [(n, t) for n in notes if n.get("status") == "open" and (cuts is None or n.get("cut") in cuts) and (t := take_of(n))]


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
    return {"action": "read", "url": url, "path": take["asset"], "out_dir": str(private_dir(room.state_dir / RAW))}


def convert(src: Path, dst: Path) -> float:
    """A downloaded take as a 24 kHz mono 16-bit WAV with silence trimmed and loudness evened out; its seconds."""
    if not shutil.which("ffmpeg"):
        raise RoomError("ffmpeg is not on PATH")
    dst = dst.resolve()   # absolute, so a name can never read as an ffmpeg option
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src.resolve()), "-vn", "-af", FILTER,
                    "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)], check=True, timeout=120)
    return round(probe_length(dst) or 0.0, 1)


def wav_name(row: dict) -> str:
    """<cut>_line<n>_<note id>.wav, with anything but letters, digits, _ and - replaced, so note data can't steer it."""
    safe = lambda v: re.sub(r"[^A-Za-z0-9_-]", "_", str(v))  # noqa: E731
    return f"{safe(row['cut'])}_line{row['line'] + 1}_{safe(row['note'])}.wav"


def private_dir(d: Path) -> Path:
    """Create a folder for takes that keeps itself out of git: they are the owner's voice."""
    d.mkdir(parents=True, exist_ok=True)
    ignore = d / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n")
    return d
