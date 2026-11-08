# CLAUDE.md

Conventions for Claude Code sessions working on cut-review. Read `docs/spec.md` first; keep it current when a
record, command or rule changes, in the same commit.

## What this repo is

- **The page** (`src/cut_review/page/review-room.html`) is published as a claude.ai artifact per room. It reads
  `room/meta`, `cuts/*`, `sets/*` and writes `notes/*`, `replies/*`, `verdicts/*` through `window.claude.use("db")`. It must stay
  generic: nothing project-specific in it. It follows the artifact page contract (no `<html>`/`<head>`, title first,
  theme tokens with light and dark, 16 px side gutter with the `max()` paddings, works at 375 px).
- **The CLI** (`src/cut_review/`) prepares inputs for Claude's `Artifact` and `ArtifactData` calls and parses
  their results. Standard library only. `room.py` (manifest + state), `parse.py` (tool-result parsers),
  `records.py` (records, versions, batch writes), `notes.py` (export, to-do, frames, fixes), `cli.py` (commands).
- **The site** (`site/`): the landing page and a demo room, the real page built from `examples/launch-cuts` with
  the harness's stand-in data layer and seeded notes (`site/build.py`). Published to GitHub Pages on every push to
  main; media are generated in CI, never committed.
- **The local recorder** (`recorder/`, experimental): a stdlib server + page, run in Docker on the owner's machine,
  that records voice takes the room can't (claude.ai blocks the mic). Same rules as the CLI: stdlib only, tested in
  `tests/test_recorder.py`.
- **The plugin** (`plugin/`, listed by `.claude-plugin/marketplace.json`): the `review-room` skill, the daily
  update hook and the band above the prompt (`plugin/hooks/band.tsx`, a hooks module). When a command
  or flow changes, update the skill in the same commit; it is how other sessions learn the loop.

## Rules

- Versions: a cut or set goes up one version only when its asset ids change (or, on a set, the words of a slide or caption), computed from the *confirmed* state
  (written to the database), never from a pending build. Every write to an existing document carries `if_version`.
- Never put a room's media, notes or `.cut-review/` state into this repo (examples keep `room.json`, a README and a script that generates placeholder media; renders stay out).
- The page treats note text as untrusted: set it with `textContent`, never `innerHTML`.
- Tests: every behaviour change gets a unit test in `tests/`; regression tests are mutation-checked (put the bug
  back, see the test fail, restore). Page changes get a run in the harness (`tests/harness/`) at desktop and 375 px,
  light and dark.

## Commands

```bash
uv sync && uv run pytest
uv run cut-review --help
python3 tests/harness/serve.py <room folder> 8765
claude plugin validate .
claude plugin test plugin                       # the band
```
