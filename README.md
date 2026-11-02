# cut-review

Review rooms for rendered videos, run by Claude.

You render videos (an edit, an animation, a set of social cuts). Claude puts them in a private claude.ai page, a
**review room**, where you watch each cut on any device, pause on a frame and type a note (or mark a time range, or box a region
of the frame), comment on still or clip
sets such as a carousel, and give each cut a verdict. When you say "apply my notes", Claude reads them, changes
whatever produced the video, re-renders, swaps the new version into the room and answers every note with what
changed. You press "Looks right" or "Still wrong".

```
owner                          review room (claude.ai)                    Claude session
pause, type a note  ───────▶   notes/<id>  {cut, t, text, status}  ───▶   cut-review notes / frames
                                                                           change source, re-render
"Looks right"       ◀───────   cut v2 + reply on the note          ◀───   uploads → build → fix
```

## Install

In Claude Code:

```
/plugin install cut-review --marketplace review-rooms/cut-review
```

or, step by step:

```bash
claude plugin marketplace add review-rooms/cut-review
claude plugin install cut-review@cut-review
```

The plugin adds the `review-room` skill, which teaches any session the whole loop. The skill runs the CLI with
`uvx --from git+https://github.com/review-rooms/cut-review cut-review` (needs [uv](https://docs.astral.sh/uv/)),
or from a checkout with `uv run --project ~/Dev/cut-review cut-review`.

## Quickstart

Ask Claude: *"Make a review room for the videos in `renders/` so I can comment on them."* Under the hood:

```bash
cut-review init --media renders --title "Launch cuts"   # room.json: one cut per video, one set per subfolder
cut-review page                                          # the page, published with the Artifact tool
cut-review link https://claude.ai/artifact/…            # remember the room
cut-review uploads                                       # files to upload, in calls of 25
cut-review assets upload-result.txt                      # record the asset ids
cut-review build                                         # records + ArtifactData batch writes
cut-review written batch-result.txt                      # record database versions
```

Later: *"Apply my notes."*

```bash
cut-review notes .cut-review/export --result export-result.txt   # to-do list from the exported notes
cut-review frames                          # the frame behind each timed note, as PNGs
# … change the source, re-render …
cut-review uploads && cut-review assets …  # only changed files
cut-review build --note poll="Counter pops 0.4 s earlier"
cut-review fix k3Jx9="Moved the counter pop 0.4 s earlier."
cut-review status
```

## Why a CLI around Claude's tools

Uploading to a claude.ai artifact and writing its database are only possible through Claude's own tools
(`Artifact`, `ArtifactData`). The CLI does everything around those calls: it lists what changed since the last
upload (by checksum), turns tool results into state, writes the room's records, bumps a cut's version only when its
video changed, keeps the database versions every write must be pinned to, and turns exported notes into a to-do
list and frames a session can look at.

## Repo

| Path | What |
| --- | --- |
| `src/cut_review/page/review-room.html` | The review page. One page for every room; all room data comes from its database. |
| `src/cut_review/` | The CLI (Python 3.10+, standard library only; ffmpeg/ffprobe optional for lengths and frames). |
| `plugin/` | The Claude Code plugin: the `review-room` skill. |
| `.claude-plugin/marketplace.json` | Makes this repo a plugin marketplace. |
| `docs/spec.md` | The design: records, state, commands. |
| `examples/` | Example rooms: `room.json` plus a script that makes placeholder media; renders and state stay local. Try `examples/launch-cuts`. |
| `tests/` | Unit tests (`uv run pytest`) and the page harness. |

## Develop

```bash
uv sync
uv run pytest
uv run cut-review --help
python3 tests/harness/serve.py <room folder> 8765   # the page against a stand-in data layer, see tests/harness
claude plugin validate .
```

MIT licensed.
