# Example: Launch cuts

A made-up product launch with two cuts and a carousel, to try the whole loop without your own renders.

- `teaser`: 9:16, 8 s, with a three-line voice-over script (one delivery cue, `[pause]`).
- `explainer`: 16:9, 12 s, with a silent alternate (the version switch under the player).
- `carousel`: a set of three stills and one clip, read from `renders/carousel/`.

```bash
./make-media.sh                      # placeholder renders (test patterns + tones) in renders/, needs ffmpeg
cut-review -C . status                # the room as the CLI sees it
python3 ../../tests/harness/serve.py . 8765   # the page locally, against a stand-in data layer
```

Then ask Claude: *"Make a review room for `examples/launch-cuts`."* The session publishes the page, uploads
the renders and writes the records, as in the main README's quickstart.

`renders/` and `.cut-review/` stay out of git.
