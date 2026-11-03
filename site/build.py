"""Build the project site: the landing page plus a demo review room that runs without claude.ai.

    examples/launch-cuts/make-media.sh        # placeholder renders, needs ffmpeg
    python3 site/build.py _site                # _site/index.html and _site/demo/

The demo is the real review page (`src/cut_review/page/review-room.html`) built from the Launch cuts example the
same way a session builds a room (`cut-review assets` then `build`), with the harness's stand-in data layer and a
few seeded notes. Notes typed in the demo live in the visitor's browser tab and are gone on reload.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "launch-cuts"
sys.path.insert(0, str(ROOT / "src"))

from cut_review.cli import main as cli  # noqa: E402

_spec = importlib.util.spec_from_file_location("harness", ROOT / "tests" / "harness" / "serve.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

BANNER = """<div id="demo-banner" style="font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#14853f;color:#fff;
padding:8px max(16px,env(safe-area-inset-left,0px));display:flex;gap:12px;flex-wrap:wrap;justify-content:space-between">
<span><b>Demo room.</b> Pause on a frame and leave a note. Notes stay in this tab only.</span>
<a href="../" style="color:#fff">← cut-review</a></div>
<script>if (window.top !== window) document.getElementById("demo-banner").hidden = true;</script>
"""

# Notes a reviewer left on the teaser, one of them already answered by Claude in v2.
NOTES = {
    "demo-fixed": {"cut": "teaser", "t": 2.1, "tEnd": None, "region": None, "item": None, "line": None, "quote": None,
                   "qStart": None, "qEnd": None, "text": "The title lands too late, the beat is on the drum hit.",
                   "status": "fixed", "reply": "Moved the title in 0.4 s earlier, on the drum hit.", "fixedIn": 2,
                   "version": 1, "by": "u_reviewer", "createdAt": "2026-11-01T10:02:00Z"},
    "demo-region": {"cut": "teaser", "t": 4.5, "tEnd": None, "region": {"x": 0.1, "y": 0.78, "w": 0.8, "h": 0.14},
                    "item": None, "line": None, "quote": None, "qStart": None, "qEnd": None,
                    "text": "The timecode box covers the captions here, move it up.", "status": "open", "reply": "",
                    "version": 2, "by": "u_reviewer", "createdAt": "2026-11-01T10:05:00Z"},
    "demo-line": {"cut": "teaser", "t": 6.0, "tEnd": 8.0, "region": None, "item": None, "line": 2,
                  "quote": "first of March", "qStart": 11, "qEnd": 25, "text": "Stress the date, slower.",
                  "status": "open", "reply": "", "version": 2, "by": "u_reviewer", "createdAt": "2026-11-01T10:07:00Z"},
    "demo-range": {"cut": "explainer", "t": 4.0, "tEnd": 7.5, "region": None, "item": None, "line": None,
                   "quote": None, "qStart": None, "qEnd": None, "text": "This stretch drags, cut a second.",
                   "status": "open", "reply": "", "version": 1, "by": "u_reviewer", "createdAt": "2026-11-01T10:09:00Z"},
}


def build_room(tmp: Path) -> tuple[dict, dict[str, Path]]:
    """Copy the example (with its renders) to tmp, record fake asset ids, build; return (seed, {id: file})."""
    room = tmp / "launch-cuts"
    shutil.copytree(EXAMPLE, room, ignore=shutil.ignore_patterns(".cut-review"))
    renders = room / "renders"
    if not renders.is_dir():
        sys.exit("No renders: run examples/launch-cuts/make-media.sh first (needs ffmpeg).")
    ids = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()[:32] for p in sorted(renders.rglob("*")) if p.is_file()}
    (tmp / "assets.json").write_text(json.dumps(ids))
    with contextlib.redirect_stdout(io.StringIO()):
        if cli(["-C", str(room), "assets", str(tmp / "assets.json")]) or cli(["-C", str(room), "build"]):
            sys.exit("cut-review couldn't build the example room")
    seed = harness.seed(room)
    teaser = seed["cuts"]["teaser"]   # show a cut that has been through one round of notes
    teaser["version"] = 2
    teaser["changes"] = [{"v": 2, "note": "Title in 0.4 s earlier, on the drum hit."}]
    seed["notes"] = NOTES
    seed["verdicts"] = {"explainer": {"state": "approved", "version": 1, "at": "2026-11-01T10:10:00Z"}}
    return seed, harness.blobs(room)


def relink(seed: dict, files: dict[str, Path]) -> str:
    """The seed as JSON with every /_blob/<id> turned into a relative _blob/<id>.<ext> that a static host can serve."""
    text = json.dumps(seed)
    for aid, f in files.items():
        text = text.replace(f'"/_blob/{aid}"', f'"_blob/{aid}{f.suffix}"')
    return text


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "site" / "index.html", out / "index.html")
    demo = out / "demo"
    shutil.rmtree(demo, ignore_errors=True)
    (demo / "_blob").mkdir(parents=True)
    with tempfile.TemporaryDirectory() as t:
        seed, files = build_room(Path(t))
        for aid, f in files.items():
            shutil.copy(f, demo / "_blob" / f"{aid}{f.suffix}")
        mock = harness.MOCK.replace("__SEED__", relink(seed, files))
    page = (ROOT / "src" / "cut_review" / "page" / "review-room.html").read_text()
    (demo / "index.html").write_text(harness.SKELETON + mock + BANNER + page + "</body></html>")
    print(f"Site in {out}: index.html, demo/ ({len(files)} media files)")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "_site").resolve())
