"""A room project on disk: the manifest (room.json) and the state (.cut-review/state.json).

The manifest is written by people (or by `cut-review init`) and says what the room shows. The state is written only
by the CLI and remembers what was uploaded and written to the room's database, so later commands can tell what
changed and pin their writes to the right versions.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST = "room.json"
STATE_DIR = ".cut-review"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MEDIA_EXT = VIDEO_EXT | IMAGE_EXT


def load_json(text: str, source: str):
    """Parse JSON, or raise RoomError naming `source` (a file, or "the input") with where it breaks."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RoomError(f"{source} is not valid JSON: {e}") from None


class RoomError(Exception):
    """A problem the person running the command can fix (missing file, bad manifest, unknown note)."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kind_of(path: str) -> str:
    """'clip' for a video file, 'still' for an image."""
    return "clip" if Path(path).suffix.lower() in VIDEO_EXT else "still"


@dataclass
class Room:
    dir: Path
    manifest: dict
    state: dict = field(default_factory=dict)

    # ---------- loading and saving
    @classmethod
    def load(cls, dir: str | os.PathLike = ".") -> "Room":
        d = Path(dir).resolve()
        mpath = d / MANIFEST
        if not mpath.exists():
            raise RoomError(f"no {MANIFEST} in {d} (run `cut-review init` first)")
        manifest = load_json(mpath.read_text(), str(mpath))
        validate_manifest(manifest)
        spath = d / STATE_DIR / "state.json"
        state = load_json(spath.read_text(), str(spath)) if spath.exists() else {}
        if not isinstance(state, dict):
            raise RoomError(f"{spath} is not a JSON object")
        state.setdefault("artifact", None)
        state.setdefault("files", {})
        state.setdefault("records", {})
        return cls(d, manifest, state)

    def save(self) -> None:
        sd = self.dir / STATE_DIR
        sd.mkdir(exist_ok=True)
        (sd / "state.json").write_text(json.dumps(self.state, indent=1, sort_keys=True) + "\n")

    @property
    def state_dir(self) -> Path:
        return self.dir / STATE_DIR

    # ---------- media
    @property
    def media_root(self) -> Path:
        m = self.manifest.get("media", ".")
        p = Path(os.path.expanduser(m))
        return (p if p.is_absolute() else self.dir / p).resolve()

    def abspath(self, rel: str) -> Path:
        return self.media_root / rel

    def relpath(self, path: str | os.PathLike) -> str | None:
        """The media-root-relative key of an absolute or relative path, or None when it lies outside the root."""
        p = Path(path)
        p = (p if p.is_absolute() else self.media_root / p).resolve()
        try:
            return p.relative_to(self.media_root).as_posix()
        except ValueError:
            return None

    def referenced_files(self) -> list[str]:
        """Every media file the manifest uses, in manifest order, without duplicates."""
        out: list[str] = []
        for c in self.manifest.get("cuts", []):
            for k in ("file", "poster"):
                if c.get(k):
                    out.append(c[k])
            for alt in c.get("alts", []):          # alternate videos of the cut (e.g. with sound)
                if alt.get("file"):
                    out.append(alt["file"])
        for s in self.manifest.get("sets", []):
            for it in set_items(self, s):
                out.append(it["file"])
        seen: set[str] = set()
        return [x for x in out if not (x in seen or seen.add(x))]

    def asset_url(self, rel: str | None) -> str | None:
        if not rel:
            return None
        f = self.state["files"].get(rel)
        return f"/_blob/{f['id']}" if f and f.get("id") else None


def set_items(room: Room, s: dict) -> list[dict]:
    """A set's items: listed explicitly (`items: [{name, file}]`) or every media file in `dir`, sorted by name."""
    if s.get("items"):
        return [{"name": it.get("name") or Path(it["file"]).stem, "file": it["file"]} for it in s["items"]]
    if s.get("dir"):
        d = room.abspath(s["dir"])
        if not d.is_dir():
            raise RoomError(f"set {s['key']}: folder {d} does not exist")
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in MEDIA_EXT and not p.name.startswith("."))
        return [{"name": p.stem, "file": (Path(s["dir"]) / p.name).as_posix()} for p in files]
    return []


def validate_manifest(m: dict) -> None:
    if not isinstance(m, dict):
        raise RoomError("room.json must be a JSON object")
    keys: set[str] = set()
    for kind in ("cuts", "sets"):
        for i, e in enumerate(m.get(kind, [])):
            k = e.get("key")
            if not k or not isinstance(k, str):
                raise RoomError(f"{kind}[{i}] has no key")
            if not all(ch.isalnum() or ch in "_-.~:@+" for ch in k) or k in (".", ".."):
                raise RoomError(f"{kind}[{i}]: key {k!r} may use letters, digits and _ - . ~ : @ + only")
            if k in keys:
                raise RoomError(f"key {k!r} is used twice")
            keys.add(k)
            if kind == "cuts" and not e.get("file"):
                raise RoomError(f"cut {k} has no file")
            if kind == "sets" and not (e.get("items") or e.get("dir")):
                raise RoomError(f"set {k} needs items or dir")
