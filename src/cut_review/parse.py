"""Parsers for the text Claude's tools return, so a session can hand a tool result straight to the CLI."""
from __future__ import annotations

import re

from .room import RoomError, load_json

# Artifact asset upload, one line per file:
#   - "/abs/path/poll.mp4" (4640162 bytes, video/mp4) → "/_blob/156dc67f538f092e0093aff2ca858328" (id 156dc…)
_ASSET = re.compile(r'"(?P<path>[^"]+)"\s*\([^)]*\)\s*(?:→|->)\s*"/_blob/(?P<id>[0-9a-f]{16,64})"')
# ArtifactData writes, one line per document:
#   - set "cuts"/"poll" (version 1)        - update "notes"/"abc" (version 4)
_WRITE = re.compile(r'(?P<op>set|update|delete)\s+"(?P<coll>[^"]+)"\s*/\s*"(?P<doc>[^"]+)"(?:\s*\(version\s+(?P<v>\d+)\))?')


# ArtifactData list/query with out_dir, one line per saved document (the files hold only the body):
#   - "probe-cli-check"  239 bytes  version 1  "/…/export/notes/probe-cli-check.json"
_LISTED = re.compile(r'^\s*-\s+"(?P<id>[^"]+)"\s+\d+\s+bytes\s+version\s+(?P<v>\d+)', re.M)


def parse_listed_versions(text: str) -> dict[str, int]:
    """{doc id: database version} from an ArtifactData list/query result that used out_dir."""
    return {m["id"]: int(m["v"]) for m in _LISTED.finditer(text)}


def parse_assets(text: str) -> dict[str, str]:
    """{path: asset id} from an upload result, or from JSON `{path: id}` / `[{path, id}]`."""
    t = text.strip()
    if t.startswith("{") or t.startswith("["):
        data = load_json(t, "the upload result")
        if isinstance(data, dict):
            return {str(k): _blob_id(str(v)) for k, v in data.items()}
        if not all(isinstance(x, dict) and "path" in x and "id" in x for x in data):
            raise RoomError("the upload result is a JSON list, but not of {path, id} objects")
        return {str(x["path"]): _blob_id(str(x["id"])) for x in data}
    return {m["path"]: m["id"] for m in _ASSET.finditer(text)}


def _blob_id(v: str) -> str:
    return v.rsplit("/", 1)[-1]


def parse_written(text: str) -> list[dict]:
    """[{op, collection, doc_id, version}] from an ArtifactData set/update/delete/batch result."""
    out = []
    for m in _WRITE.finditer(text):
        out.append({"op": m["op"], "collection": m["coll"], "doc_id": m["doc"],
                    "version": int(m["v"]) if m["v"] else None})
    return out
