# Local recorder (experimental)

claude.ai pages can't use the microphone, so a review room can't record how a script line should sound. This
recorder runs on your own computer instead: a small page at `http://localhost:8790` that lists the open notes on
script lines and records a take for each one, straight into the room project. Nothing leaves your computer.

## Run it

From the room project (the folder with `room.json`), after exporting the notes with `cut-review notes …`:

```bash
docker build -f /path/to/cut-review/recorder/Dockerfile -t cut-review-recorder /path/to/cut-review
mkdir -p .cut-review/takes/local
docker run --rm -p 127.0.0.1:8790:8790 --user "$(id -u):$(id -g)" \
  -v "$PWD:/room:ro" -v "$PWD/.cut-review/takes/local:/room/.cut-review/takes/local" cut-review-recorder
```

Open `http://localhost:8790` in Safari or Chrome on the same computer, allow the microphone, and record.
Without Docker: `python3 /path/to/cut-review/recorder/server.py .` (Python 3.10+).

- The room project is mounted read-only; only `.cut-review/takes/local/` is writable. Takes are saved there as
  `<note id>.webm` (Chrome) or `<note id>.m4a` (Safari), one per note; the folder keeps itself out of git.
- The port is published on `127.0.0.1` only, and the server answers only to `localhost`.
- `cut-review takes` converts these takes to WAVs and `takes.json` like the room's takes, with no downloads.
- A phone can't use it yet: browsers allow the microphone only on `localhost` or HTTPS.

## API

| Request | Does |
| --- | --- |
| `GET /api/notes` | The open notes on script lines: `{note, cut, line, from, to, text, words, noteText, take}`, in the room's cut order. 409 when the notes weren't exported. |
| `PUT /api/takes/<note id>` | Saves the body (`audio/webm`, `audio/mp4` or `audio/ogg`, at most 20 MiB) as the note's take, replacing any earlier one. |
| `GET /api/takes/<note id>` | The take, for playback. |
| `DELETE /api/takes/<note id>` | Removes the take. |
