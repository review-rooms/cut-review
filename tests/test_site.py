"""The project site's build: the demo room's media links must work on a static host."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("site_build", ROOT / "site" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def test_relink_makes_blob_urls_relative_with_extensions():
    seed = {"cuts": {"a": {"video": "/_blob/abc123", "poster": "/_blob/def456", "alts": [{"video": "/_blob/abc123"}]}}}
    files = {"abc123": Path("r/a.mp4"), "def456": Path("r/a.poster.png")}
    out = json.loads(build.relink(seed, files))
    assert out["cuts"]["a"]["video"] == "_blob/abc123.mp4"
    assert out["cuts"]["a"]["poster"] == "_blob/def456.png"
    assert out["cuts"]["a"]["alts"][0]["video"] == "_blob/abc123.mp4"


def test_seeded_notes_quote_matches_the_line():
    line = json.loads((ROOT / "examples" / "launch-cuts" / "room.json").read_text())["cuts"][0]["script"][2]["text"]
    for n in build.NOTES.values():
        if n["quote"]:
            assert line[n["qStart"]:n["qEnd"]] == n["quote"]
