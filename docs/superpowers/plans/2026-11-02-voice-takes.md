# Voice takes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner records how a script line should sound from the note form (phone recorder or a file), the page
keeps only the sound and stores it on the note, and the CLI exports each take as a 24 kHz mono WAV next to the exact
words.

**Architecture:** The page gets a self-contained "keep only the sound" section (mp4box.js parses, the page writes a
plain `M4A ` mp4 itself; Web Audio + MediaRecorder as fallback) and a take row in the composer that shows only for
notes on a script line. Notes gain a `take` field. The CLI gets `take_of` and a to-do line in `notes.py`, and a new
`takes.py` behind a `takes` command that prints `Artifact` read calls, then converts downloaded files with ffmpeg.

**Tech Stack:** Python 3.10+ stdlib (CLI), pytest via uv, ffmpeg/ffprobe, plain JS in one HTML page, mp4box.js
0.5.2 from jsDelivr.

**Spec:** `docs/superpowers/specs/2026-11-02-voice-takes-design.md` (read it first; this plan argues from it).

## Global Constraints

- CLI stays standard library only; ffmpeg/ffprobe are optional tools, needed only by `takes` when converting.
- Page stays generic and follows the artifact page contract (`<title>` first, light/dark tokens, `max()` side
  gutters, works at 375 px). Note text, quotes and file names go in with `textContent`; the page never contains
  `innerHTML`.
- mp4box.js is the page's only external script: `https://cdn.jsdelivr.net/npm/mp4box@0.5.2/dist/mp4box.all.min.js`.
- Asset store: upload type `video/mp4` or `video/webm` only; 20 MiB cap (`20 * 1024 * 1024` bytes).
- Record field: `take` = `null` or `{asset, seconds, type}`; `asset` 32 lowercase hex; only on notes with `line`.
- WAV: 24 kHz, mono, 16-bit PCM, `loudnorm` to −20 LUFS, leading/trailing silence trimmed; name
  `<cut>_line<n>_<note id>.wav` with `n` 1-based; default out dir `.cut-review/takes`, raw downloads in
  `.cut-review/takes/raw`.
- Exact copy (from the spec): buttons **🎙 Record how it should sound**, **Pick a file**, **Redo**, **Remove**;
  progress "Keeping only the sound…"; refusal "This recording's format can't be used; record again with the phone,
  or pick an m4a/mp3/wav."; size refusal "Too long: keep a take under a few minutes."
- Every behaviour change has a unit test; regression tests are mutation-checked. Page changes run in the harness at
  desktop and 375 px, light and dark. `docs/spec.md` and the skill change in the same commit as the behaviour.
- Commits use the repo's configured identity (`cut-review contributors`); never set another.

## Review Focus

1. **Line detached or cut switched with a take attached** (✕ on the line target, picking another cut): the take is
   dropped and its uploaded asset deleted, so no note without `line` carries a `take`. Test in Task 5.
2. **Saving before the upload finishes:** Add note waits for the upload and writes the take; a failed upload keeps
   the text and take in the form with the error shown, nothing written. Test in Task 5.
3. **A note whose line no longer exists in the script** (script shortened since): `takes` still converts it, with
   `text` `""`, `from`/`to` `null`, `words` the note's quote. Test in Task 2.
4. **A take on a resolved, fixed or won't-fix note:** not downloaded or converted, not in `takes.json`. Test in
   Task 2.
5. **A malformed `take`** (missing asset, non-hex id, string seconds) from an old or hand-edited note: ignored by
   `take_of`, so the to-do and `takes` skip it, and the page shows no player. Tests in Tasks 1 and 5.

---

### Task 1: `take_of` and the to-do line

**Files:**
- Modify: `src/cut_review/notes.py` (new `take_of`, one line in `todo`)
- Test: `tests/test_cut_review.py`

**Interfaces:**
- Produces: `take_of(note: dict) -> dict | None`: returns `{"asset": str, "seconds": float, "type": str}` when
  `note["take"]` is a dict whose `asset` matches `^[0-9a-f]{32}$`, `seconds` is an int/float ≥ 0 (not bool), `type`
  is `"video/mp4"` or `"video/webm"`, and `script_line(note)` is not None; else `None`.

- [ ] **Step 1: Write the failing tests**

```python
A = "39bb1bc8def01eca67a6f983358b3c0d"

def test_take_of_accepts_only_well_formed_takes_on_script_lines():
    ok = {"line": 0, "take": {"asset": A, "seconds": 4.2, "type": "video/mp4"}}
    assert take_of(ok) == {"asset": A, "seconds": 4.2, "type": "video/mp4"}
    for bad in ({"asset": "xyz", "seconds": 1, "type": "video/mp4"}, {"asset": A, "seconds": "4", "type": "video/mp4"},
                {"asset": A, "seconds": 1, "type": "audio/mp4"}, {"seconds": 1, "type": "video/mp4"}, "take", None):
        assert take_of({"line": 0, "take": bad}) is None
    assert take_of({"line": None, "take": ok["take"]}) is None

def test_todo_shows_a_take_under_its_line(room_dir, tmp_path):
    # note on script line 0 with a take → "  take: 4.2 s (asset 39bb…)" right after its "  line:" row
```

The second test builds the note with `export()` like `test_todo_shows_script_lines_and_quotes`, runs `todo`, and
asserts the output contains `"  line: Hook\n  take: 4.2 s (asset 39bb…)"`, and that a note with
`"take": {"asset": "nope"}` prints no `take:` row.

- [ ] **Step 2: Run them, expect ImportError / assertion failure**

Run: `uv run pytest tests/test_cut_review.py -k "take_of or todo_shows_a_take" -v`

- [ ] **Step 3: Implement `take_of` and the row** — in `todo`, after the `line:` row: `f"  take: {t['seconds']:.1f} s (asset {t['asset'][:4]}…)"`.

- [ ] **Step 4: Run the whole suite, expect all pass; mutation-check** (make `take_of` skip the hex check, see the
  first test fail, restore).

Run: `uv run pytest -q`

- [ ] **Step 5: Commit** (`docs/spec.md`: add the `take` field to the `notes/<id>` record row, copying the spec's
  table text.)

```bash
git add src/cut_review/notes.py tests/test_cut_review.py docs/spec.md
git commit -m "Notes: take field and its line in the to-do list"
```

### Task 2: `takes` command, part 1: what to download, and `takes.json` rows

**Files:**
- Create: `src/cut_review/takes.py`
- Modify: `src/cut_review/cli.py` (`cmd_takes`, parser `takes`)
- Test: `tests/test_cut_review.py`

**Interfaces:**
- Consumes: `take_of`, `spoken`, `quote_span`, `script_line`, `saved_notes` from `notes.py`.
- Produces (in `takes.py`):
  - `RAW = "takes/raw"` (under `room.state_dir`).
  - `take_row(room: Room, note: dict) -> dict`: `{"note", "cut", "line", "from", "to", "text", "words", "noteText"}`
    where `line` is the 0-based index, `from`/`to` come from the script line (or `None` if the line is out of range),
    `text` is `spoken(line text)` (or `""`), `words` is the span from `quote_span` if found, else the note's `quote`
    if non-empty, else `text`.
  - `raw_file(room: Room, take: dict) -> Path | None`: the downloaded file `RAW/<asset>.*`, or None.
  - `read_call(room: Room, take: dict) -> dict`: `{"action": "read", "url": room.state["artifact"], "path": asset,
    "out_dir": str(room.state_dir / RAW)}`; raises `RoomError("no room linked (run `cut-review link URL`)")` when
    no artifact is linked.
  - `open_takes(notes: list[dict]) -> list[tuple[dict, dict]]`: `(note, take)` for notes with `status == "open"`
    and a `take_of`.
- CLI: `cut-review takes [--out DIR]` reads `saved_notes(room)`. For each open take without a raw file it collects
  `read_call`s; it prints them as one JSON list under the line
  `Download these with the Artifact tool, one call each, then run \`cut-review takes\` again:`. With no open takes it
  prints `No open notes with a take.` Conversion comes in Task 3.

- [ ] **Step 1: Write the failing tests**

```python
def test_takes_prints_a_read_call_per_open_take(room_dir, tmp_path, capsys):
    # link the room, save notes: open+take (line 0), resolved+take, open without take
    # run(room_dir, "takes") → one call: {"action": "read", "url": <linked url>, "path": A,
    #   "out_dir": str(room_dir / ".cut-review/takes/raw")}

def test_takes_refuses_without_a_linked_room(room_dir): ...   # RoomError mentioning `cut-review link`

def test_take_row_words_for_spans_gone_words_and_gone_lines(room_dir):
    # script line 0 "Hook": quote "Hook" qStart 0 qEnd 4 → words "Hook", from 0, to 3, text "Hook"
    # quote "Gone" → words "Gone"; no quote → words "Hook"
    # line 5 (out of range) → text "", from None, to None, words = quote
```

- [ ] **Step 2: Run, expect failures.** `uv run pytest -k "takes or take_row" -v`
- [ ] **Step 3: Implement `takes.py` and `cmd_takes`** following `cmd_frames`'s style (load room, saved notes, print).
- [ ] **Step 4: Full suite passes; mutation-check** `open_takes` (drop the status filter → first test fails).
- [ ] **Step 5: Commit** with `docs/spec.md` (the `takes` command row, download half) and `SKILL.md` untouched until
  Task 3. Also amend the voice-takes spec's `words` sentence: when the note's words left the line, `words` is the
  note's quote (what the owner recorded), not the whole line.

```bash
git add src/cut_review/takes.py src/cut_review/cli.py tests/test_cut_review.py docs/spec.md
git commit -m "takes: list the Artifact reads that download open notes' voice takes"
```

### Task 3: `takes` command, part 2: convert to WAV and write `takes.json`

**Files:**
- Modify: `src/cut_review/takes.py`, `src/cut_review/cli.py`
- Modify: `plugin/skills/review-room/SKILL.md` (new section "Notes with a voice take"), `docs/spec.md`
- Test: `tests/test_cut_review.py`

**Interfaces:**
- Produces: `convert(src: Path, dst: Path) -> float`: runs ffmpeg, returns the WAV's length in seconds
  (`records.probe_length`, rounded to 0.1). Raises `RoomError("ffmpeg is not on PATH")` if missing.
  The filter chain, in this order:
  `silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-20`
  then `-ar 24000 -ac 1 -c:a pcm_s16le`.
- `cmd_takes` converts every open take whose raw file exists into `DIR/<cut>_line<n>_<id>.wav` (DIR = `--out` or
  `room.state_dir / "takes"`), and writes `DIR/takes.json` as the list of `take_row(...) | {"wav": <file name>,
  "seconds": <float>}` (key order as in the spec's example). It prints one line per WAV
  (`<path>  ← <cut> line <n>: <words[:60]>`), then the pending read calls, if any, as in Task 2. Takes still to
  download are not in `takes.json`.

- [ ] **Step 1: Write the failing tests** (skip when `ffmpeg` is missing, like `test_frames_…`)

```python
def test_takes_converts_downloads_to_24k_mono_wav_and_lists_them(room_dir, capsys):
    # make RAW/<A>.mp4 with ffmpeg: sine 440 Hz, 3 s, 48 kHz stereo AAC, with 1 s of silence before it, very quiet (volume=0.05)
    # run takes → .cut-review/takes/poll_line1_<id>.wav exists
    # ffprobe: sample_rate 24000, channels 1, codec pcm_s16le; duration < 3.6 (leading silence trimmed)
    # takes.json == [{"note": id, "cut": "poll", "line": 0, "from": 0, "to": 3, "text": "Hook", "words": "Hook",
    #                 "wav": "poll_line1_<id>.wav", "seconds": <float>, "noteText": ...}]
    # no read call printed

def test_takes_out_dir_and_mixed_downloaded_and_missing(room_dir, tmp_path, capsys):
    # two open takes, one downloaded: --out tmp_path/x → one WAV + takes.json in x, one read call printed
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement `convert` and the conversion loop.**
- [ ] **Step 4: Full suite passes; mutation-check** (drop `-ac 1` → the channel assertion fails).
- [ ] **Step 5: Skill and spec.** The new SKILL.md section: export notes → `cut-review takes` → run the printed
  `Artifact` reads → `cut-review takes` again → give each WAV and its `words` to the project's voice step as the
  reference for how the line should sound. Rules copied from the spec: a take is the owner's voice, used only as a
  reference for that line; never publish, share or train on it; never copy takes into the repo. Mention the
  `take:` row in "Apply the owner's notes". `docs/spec.md`: the conversion half of `takes`.
- [ ] **Step 6: `claude plugin validate .` passes; commit.**

```bash
git add src/cut_review/takes.py src/cut_review/cli.py tests/test_cut_review.py plugin/skills/review-room/SKILL.md docs/spec.md
git commit -m "takes: convert voice takes to 24 kHz mono WAV and write takes.json"
```

### Task 4: Page: keep only the sound (`audioOnly` and the plain mp4 writer) + harness support

**Files:**
- Modify: `src/cut_review/page/review-room.html` (mp4box `<script src>` right after the `<style>` block; one new
  section `// ---------- keeping only the sound` inside the page script)
- Modify: `tests/harness/serve.py` (an `assets` stand-in), create `tests/harness/make-takes.sh`
- Test: `tests/test_cut_review.py` (static page checks)

**Interfaces:**
- Produces (page script, in scope for Task 5):
  - `wakeAudio(): void`: creates/resumes the shared `AudioContext` (call it from the tap that opens a picker).
  - `audioOnly(file: File) → Promise<{blob: Blob, seconds: number}>`, `blob.type` is `"video/mp4"` or `"video/webm"`.
    Rejects with `Error` whose `name` is `"Unusable"` (show the format refusal copy) or `"TooLong"` (size copy).
  - `writeM4a({timescale, sampleRate, channels, esds: Uint8Array, sizes: number[], durations: number[], data:
    Uint8Array}) → Blob`.
- Harness: `assets` stand-in on `window.claude.use("assets")`: `upload(blob, {type})` POSTs the bytes to
  `/_assets?type=…`; `serve.py` writes them to `<room>/.cut-review/harness-assets/<32-hex id>` and answers
  `{id, url: "/_blob/<id>", sizeBytes, contentType}`, and serves those at `/_blob/<id>` with the stored type.
  `delete(id)` removes the file. `?noassets` leaves `assets` out. `window.__assets` lists the uploads.

How `audioOnly` decides, in order (from the spec): parse with mp4box; first audio track with codec starting `mp4a`
→ extract every sample (`setExtractionOptions(id, null, {nbSamples: Infinity})`, collect in `onSamples`) and
`writeM4a`, taking `esds` bytes from the track's `stsd` entry (`entry.esds.write(DataStream)`, big-endian). Not
mp4/QuickTime, or no AAC track → `ctx.decodeAudioData` and re-record through `MediaRecorder` (`audio/mp4` if
supported, else `audio/webm`) in real time; stored type `video/mp4` or `video/webm` accordingly. Decode fails, or
no audio → `Unusable`. Result over 20 MiB → `TooLong`.

`writeM4a` box layout (moov before mdat, so `stco` holds `ftyp size + moov size + 8`):
`ftyp(major "M4A ", minor 0, compatible "M4A ","mp42","isom")`, `moov(mvhd, trak(tkhd(enabled, volume 1.0),
mdia(mdhd(timescale), hdlr("soun"), minf(smhd, dinf(dref(url self-contained)), stbl(stsd(mp4a(channels, 16-bit,
sampleRate<<16, esds)), stts(run-length of durations), stsc(1 entry: 1, sizes.length, 1), stsz(per-sample sizes),
stco(1 chunk))))))`, `mdat(data)`. All durations in the track timescale; mvhd may use the same timescale.

- [ ] **Step 1: Write the failing static test**

```python
def test_page_keeps_only_the_sound_without_reencoding(room_dir, capsys):
    html = page_html(room_dir)          # helper: run "page -o" and read it (factor out of the existing tests)
    assert html.count("<script src=") == 1 and "mp4box@0.5.2/dist/mp4box.all.min.js" in html
    assert '"M4A "' in html and "function writeM4a(" in html and "async function audioOnly(" in html
    assert "This recording's format can't be used; record again with the phone, or pick an m4a/mp3/wav." in html
    assert "innerHTML" not in html and html.startswith("<title>")
```

- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Write the fixtures script** `tests/harness/make-takes.sh DIR`: ffmpeg makes `iphone.mov` (libx265
  `-tag:v hvc1` 720x1280 + AAC 48 kHz mono, 5 s speech-like tone), `voice.m4a` (AAC), `voice.ogg` (vorbis),
  `old.3gp` (libopencore_amrnb, 8 kHz mono). Outputs stay out of git (write into DIR, default a temp dir).
- [ ] **Step 4: Implement the harness `assets` stand-in, then `wakeAudio`, `audioOnly`, `writeM4a`.**
- [ ] **Step 5: Static test passes; full suite passes.**
- [ ] **Step 6: Harness check.** Build `examples/launch-cuts` with fake asset ids as in its README, serve it, and in
  the browser call `audioOnly` on each fixture (fetch it into a `File`), upload the result with the stand-in, then:
  - `iphone.mov` and `voice.m4a` → `video/mp4`; `ffprobe` on the stored file shows one AAC stream, duration within
    0.1 s of the source, and `ffprobe -v trace` (or a box dump) shows no `moof`; an `<audio>` element loads it
    (`loadedmetadata` fires, `duration` finite).
  - `voice.ogg` → plays, type `video/mp4` or `video/webm`.
  - `old.3gp` → rejects with `name === "Unusable"`.
- [ ] **Step 7: Commit.**

```bash
git add src/cut_review/page/review-room.html tests/harness/serve.py tests/harness/make-takes.sh tests/test_cut_review.py
git commit -m "Page: keep only the sound of a recording, as a plain M4A (track copy) or re-recorded"
```

### Task 5: Page: the take in the note form, on saved notes and in the script

**Files:**
- Modify: `src/cut_review/page/review-room.html` (composer markup + CSS, composer code, `addNote`, `renderNotes`,
  `renderScriptMarks`, `boot`, line/cut reset)
- Test: `tests/test_cut_review.py`; harness run

**Interfaces:**
- Consumes: `wakeAudio`, `audioOnly` (Task 4); the harness `assets` stand-in.
- Page state: `S.assets` (namespace or null, set in `boot` with `use("assets")`); `S.take` = `null` or
  `{blob, seconds, type, upload: Promise<{id}>, url}` while composing.
- Writes: `addNote` adds `take: S.line && S.take ? {asset: id, seconds: Math.round(seconds * 10) / 10, type} :
  null` after awaiting `S.take.upload`.

Behaviour (spec "The owner's flow"):
- `#takeRow` under the textarea: two `<label>`s for hidden file inputs (`#takeCap` `accept="audio/*" capture`,
  `#takePick` `accept="audio/*,video/*"`), with the exact copy. Shown only when `S.line && S.assets && S.canWrite`;
  each label's click calls `wakeAudio()`.
- After a file is picked: hint "Keeping only the sound…", then a player (`<audio controls>` on an object URL), the
  length, **Redo** (opens the recorder again) and **Remove**. The upload starts at once. Refusals show their copy
  in `#composerHint`; nothing is uploaded.
- Redo, Remove, detaching the line (`#b-unline`), switching cut, and a successful save clear `S.take`; all but the
  save also `S.assets.delete(id)` the uploaded asset (ignore errors) and revoke the object URL.
- Add note stays disabled while there's no text; with a take still uploading it waits (button disabled, hint
  "Keeping only the sound…"). A failed upload keeps the text and the take, shows the error via `onWriteError`, and
  writes nothing.
- Saved notes with `take_of`-equivalent valid takes (same rules as Task 1, in JS) show a `🎙` button in the card's
  top row and an `<audio controls preload="none" src="/_blob/<asset>">` under the body. Script rows whose open or
  fixed notes have a take show `🎙` beside the note count.
- Deleting your own open note with a take also deletes its asset (ignore errors).

- [ ] **Step 1: Write the failing static test**

```python
def test_page_offers_takes_only_in_the_note_form(room_dir, capsys):
    html = page_html(room_dir)
    assert html.count("🎙 Record how it should sound") == 1 and "Pick a file" in html
    assert 'id="takeCap" accept="audio/*" capture' in html and 'id="takePick" accept="audio/*,video/*"' in html
    assert "take: S.line && S.take" in html and 'use("assets")' in html
```

- [ ] **Step 2: Run, expect failure. Step 3: Implement. Step 4: Full suite passes.**
- [ ] **Step 5: Harness run** (desktop and 375 px, light and dark), with the `iphone.mov` fixture via the picker
  (`form_input`/file upload into `#takePick`):
  - No take buttons on a fresh form or on a set; they appear after tapping a script word, and disappear on ✕.
  - Record → player plays; Redo then Remove → `window.__assets` shows each upload deleted.
  - Save → `window.__store.notes` has `take: {asset (32 hex), seconds, type: "video/mp4"}` and `line`; the card shows
    🎙 and its player loads from `/_blob/<id>`; the script row shows 🎙.
  - Detach the line with a take attached → asset deleted, saved note has `take: null` and `line: null`.
  - `?noassets` → no take buttons anywhere; notes still save.
  - A seeded note with `take: {asset: "nope"}` shows no player and no error.
- [ ] **Step 6: Commit** with `docs/spec.md` (page behaviour: take row, marks, asset deletion).

```bash
git add src/cut_review/page/review-room.html tests/test_cut_review.py docs/spec.md
git commit -m "Page: record how a script line should sound, on the note"
```

### Task 6: Phone check (needs the owner)

- [ ] **Step 1:** Ask the owner (AskUserQuestion) which real room to update with the new page, or whether to publish
  a fresh test room from `examples/launch-cuts`. Publishing waits for that answer.
- [ ] **Step 2:** The owner, in the Claude iOS app: tap a script word, record, play back in the form, save, play the
  saved note's take.
- [ ] **Step 3:** Export notes, run `cut-review notes …`, `cut-review takes`, the printed reads, `cut-review takes`
  again; listen to the WAV and send it to the owner.
- [ ] **Step 4:** Record the result in the spec's findings table; commit.
