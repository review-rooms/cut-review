"""Turn a room's manifest and uploaded assets into its database records, and the ArtifactData writes for them.

Versions: a cut or set starts at version 1 and goes up by one when the asset ids it shows change (a re-render
uploaded under a new id). Each bump adds a line to its change log. The CLI keeps two copies of every record's
bookkeeping in the state: `confirmed` (what the database is known to hold, set by `cut-review written`) and
`pending` (what the last `build` prepared). Builds compute from `confirmed`, so building twice before writing never
bumps a version twice.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .room import Room, RoomError, kind_of, set_items

BATCH_MAX = 50  # ArtifactData batch limit


def probe_length(path: Path) -> float | None:
    """Duration in seconds via ffprobe, or None when ffprobe is missing or fails."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        return round(float(out), 2)
    except (subprocess.SubprocessError, ValueError):
        return None


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _versioned(room: Room, rid: str, assets: list[str | None], note: str | None) -> tuple[int, list[dict], list[dict]]:
    """(version, changes, history) from the confirmed state; history gains the confirmed version on a bump."""
    conf = room.state["records"].get(rid, {}).get("confirmed")
    if not conf:
        return 1, [], []
    version, changes, history = conf["version"], list(conf.get("changes", [])), list(conf.get("history", []))
    if conf.get("assets") != assets:
        past = {"v": version, "note": next((c["note"] for c in changes if c.get("v") == version), "")}
        snap = conf.get("snap")
        if snap:
            history.append({**past, **snap})
        elif rid.startswith("cuts/"):   # state from before snapshots: the old ids are all we know
            old = conf.get("assets") or [None, None]
            history.append({**past, "video": old[0], "poster": old[1] if len(old) > 1 else None})
        version += 1
        changes.append({"v": version, "note": note or "re-rendered"})
    return version, changes, history


def build_records(room: Room, notes: dict[str, str] | None = None, probe=probe_length) -> list[tuple[str, str, dict, list]]:
    """[(collection, doc_id, data, assets)] for room/meta, every cut and every set.

    Raises RoomError naming every file that has no asset id yet (run `uploads` and `assets` first).
    """
    notes = notes or {}
    m = room.manifest
    missing = [rel for rel in room.referenced_files() if not room.asset_url(rel)]
    if missing:
        raise RoomError("not uploaded yet: " + ", ".join(missing) + " (run `cut-review uploads`)")

    out: list[tuple[str, str, dict, list]] = []
    meta = {"title": m.get("title", "Review room"), "subtitle": m.get("subtitle", ""),
            "scriptLabel": m.get("scriptLabel", "Script"), "groups": m.get("groups", [])}
    out.append(("room", "meta", meta, []))

    order = 0
    for c in m.get("cuts", []):
        video, poster = room.asset_url(c["file"]), room.asset_url(c.get("poster"))
        alts = [{"key": alt["key"], "label": alt.get("label", alt["key"]), "video": room.asset_url(alt["file"])}
                for alt in c.get("alts", [])]
        assets = [video, poster] + [alt["video"] for alt in alts]   # a new alternate is a new version too
        version, changes, history = _versioned(room, f"cuts/{c['key']}", assets, notes.get(c["key"]))
        length = c.get("length")
        if length is None:
            length = probe(room.abspath(c["file"]))
        data = {
            "title": c.get("title", c["key"]), "short": c.get("short", c.get("title", c["key"])),
            "group": c.get("group", ""), "order": order, "aspect": c.get("aspect", "9:16"),
            "tags": list(c.get("tags", [])), "description": c.get("description", ""),
            "length": length, "video": video, "poster": poster,
            "version": version, "changes": changes, "script": list(c.get("script", [])),
        }
        if history:   # left out while empty, so rooms built before history don't rewrite every record
            data["history"] = history
        if alts:
            data["alts"] = alts
            for k in ("videoLabel", "altDefault"):
                if c.get(k):
                    data[k] = c[k]
        out.append(("cuts", c["key"], data, assets))
        order += 1

    for s in m.get("sets", []):
        items = [{"name": it["name"], "kind": kind_of(it["file"]), "url": room.asset_url(it["file"])}
                 for it in set_items(room, s)]
        assets = [it["url"] for it in items]
        version, changes, history = _versioned(room, f"sets/{s['key']}", assets, notes.get(s["key"]))
        data = {
            "title": s.get("title", s["key"]), "short": s.get("short", s.get("title", s["key"])),
            "group": s.get("group", ""), "order": order, "aspect": s.get("aspect", "4:5"),
            "description": s.get("description", ""), "items": items,
            "version": version, "changes": changes,
        }
        if history:
            data["history"] = history
        out.append(("sets", s["key"], data, assets))
        order += 1
    return out


def stage(room: Room, records: list[tuple[str, str, dict, list]], only_changed: bool = True) -> list[dict]:
    """Write each record to .cut-review/out/, remember it as pending, and return the batch writes.

    With only_changed, records whose content equals what the database is known to hold are left out.
    """
    outdir = room.state_dir / "out"
    outdir.mkdir(parents=True, exist_ok=True)
    writes = []
    for coll, doc, data, assets in records:
        rid = f"{coll}/{doc}"
        rec = room.state["records"].setdefault(rid, {})
        h = _hash(data)
        conf = rec.get("confirmed")
        snap = ({k: data.get(k) for k in ("video", "poster", "script", "length")} if coll == "cuts"
                else {"items": data["items"]} if coll == "sets" else None)
        if only_changed and conf and conf.get("hash") == h:
            rec.pop("pending", None)
            if snap:
                conf["snap"] = snap   # the database holds exactly this, so a later bump can keep it in history
            continue
        path = outdir / f"{coll}__{doc}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        rec["pending"] = {"hash": h, "version": data.get("version"), "assets": assets, "changes": data.get("changes", []),
                          "history": data.get("history", []), "snap": snap}
        w = {"op": "set", "collection": coll, "doc_id": doc, "file_path": str(path)}
        if conf and conf.get("db"):
            w["if_version"] = conf["db"]
        writes.append(w)
    return writes


def confirm(room: Room, written: list[dict]) -> list[str]:
    """Apply an ArtifactData result: pending records become confirmed with their database version.

    Notes written by `fix` get their new version in .cut-review/notes.json. Returns what was recorded.
    """
    done = []
    for w in written:
        rid = f"{w['collection']}/{w['doc_id']}"
        if w["collection"] == "notes":
            from .notes import set_note_version
            if set_note_version(room, w["doc_id"], w["version"]):
                done.append(rid)
            continue
        rec = room.state["records"].get(rid)
        if rec is None:
            continue
        if w["op"] == "delete":
            room.state["records"].pop(rid, None)
            done.append(rid)
            continue
        pend = rec.pop("pending", None)
        conf = rec.get("confirmed", {})
        if pend:
            conf = {**conf, **pend}
        if w["version"] is not None:
            conf["db"] = w["version"]
        rec["confirmed"] = conf
        done.append(rid)
    return done


def chunks(writes: list[dict], n: int = BATCH_MAX) -> list[list[dict]]:
    return [writes[i:i + n] for i in range(0, len(writes), n)]
