# Voice takes on script notes: design

Approved in chat 2 Nov 2026. Builds on the word and character notes (`line`, `quote`, `qStart`/`qEnd`).

## Goal

The owner hears a generated voice-over line that sounds wrong, and shows how it should sound: they record
themselves saying the line (or the words they selected) with the intended intonation, from the review room, on
the phone. The take is attached to the note. A Claude session exports it as reference audio next to the exact
words, so the project's voice step can re-generate the line with the persona's voice following that intonation.
Converting the owner's intonation into the persona's voice is the project's job, not cut-review's.

## What the phone tests showed (2 Nov 2026, test page `mic-probe`, three rounds)

| Finding | Evidence |
| --- | --- |
| A page cannot use the live microphone: `getUserMedia` rejects `NotAllowedError` in the Claude iOS app and in Chrome on iOS; the runtime roster has no microphone capability. | test 1 |
| `<input type=file accept="audio/*" capture>` opens the phone's recorder. On iPhone (Claude app and Chrome) that is the camera, which returns a `.MOV` (HEVC video + AAC audio, about 100 KB/s). On Android it opens the sound recorder, or the Files picker when there is none. | tests 1–3, Android emulator |
| Web Audio cannot decode an iPhone `.MOV` (`decodeAudioData` → `EncodingError`), and a `<video>` with sound cannot play after the picker returns (`NotAllowedError`), so neither can be used to re-encode. | iPhone, test 3 |
| Copying the AAC track out of the container works on iPhone, Android and desktop: 30.2 s, 483 KB, read back from the asset store, converted by ffmpeg to WAV with sound throughout. | iPhone + Android emulator + Mac, test 3 |
| The copied track written as a fragmented mp4 (mp4box.js segmentation) plays in Chrome but not in the iPhone's `<audio>` ("Error"). A plain (non-fragmented) mp4 is needed for playback in the room. | iPhone, test 3 |
| The asset store accepts only `video/mp4` and `video/webm` for media (no audio types, no QuickTime), 20 MiB per file. An audio-only mp4 stored as `video/mp4` plays as audio. | `assets.d.ts`, tests 2–3 |
| AMR (`.3gp` from old Android recorders) cannot be read by any method in Chrome. | Android emulator |
| Takes come in quiet (iPhone camera mic at arm's length: peak −22.5 dB, mean −41.8 dB). | test 3 take |

## The owner's flow (page)

1. Start a note on a script line, a word or a span, as today. The note form shows, under the text box,
   **🎙 Record how it should sound** and **Pick a file**. Nothing about recording shows anywhere else: no buttons
   on script lines, nothing in the cut view.
2. Record opens the phone's recorder (`<input type=file accept="audio/*" capture>`); Pick a file opens the picker
   (`accept="audio/*,video/*"`, no `capture`), for a Voice Memo or any audio or video file.
3. The page keeps only the sound and shows it in the form as a player with its length, plus **Redo** and
   **Remove**. One take per note. While it works, the form says "Keeping only the sound…"; saving the note waits
   for the upload.
4. Saving the note uploads the take and writes it on the note. A saved note with a take shows a 🎙 mark in the
   notes list and the script panel, and a player in the note. A note's take is fixed once saved (Remove +
   new note to change it), like the rest of a note.
5. Only people who can edit the room record takes (the asset store is granted to Editors and up); for anyone else
   the two buttons do not show.

Writing a note's text stays required; the take is an addition ("say it like this"), never the whole note.

## Keeping only the sound (page)

`audioOnly(file) → {blob, seconds}`, in a small self-contained part of the page:

1. Parse the file as mp4/QuickTime (mp4box.js, pinned version from jsDelivr, the page's only external script).
   Take the first audio track. If it is AAC (`mp4a`), copy its samples, untouched, into a **plain mp4**
   (`ftyp` `M4A `, `moov` with one sound track, `mdat`): the page writes the boxes itself from the track's
   sample sizes, durations and decoder config (`esds`). No re-encoding, so it is instant and lossless, and
   the picture never leaves the phone.
2. If the file is not mp4/QuickTime or has no AAC track (an `.ogg`, a `.webm`, a `.wav`), decode it with Web
   Audio and re-record it with `MediaRecorder` (`audio/mp4` where supported, else `audio/webm`), in real time.
   The audio context is created in the tap that opens the picker (iOS needs a gesture).
3. Anything else (AMR, a file with no sound) is refused in the form: "This recording's format can't be used;
   record again with the phone, or pick an m4a/mp3/wav." Nothing is uploaded.
4. Over 20 MiB after step 1 or 2 (about 20 minutes of AAC) is refused with "Too long: keep a take under a few
   minutes."

Upload: `assets.upload(blob, {type: "video/mp4" | "video/webm"})`, the container type the store accepts.

## Record (`notes/<id>`): new field

| Field | Value |
| --- | --- |
| `take` | `null`, or `{asset, seconds, type}`: `asset` is the asset id (32 hex), `seconds` the take's length, `type` the stored content type (`video/mp4` or `video/webm`). Only on notes with `line` set. |

Everything else about notes is unchanged, and pages built before this ignore the field.

## CLI

- `notes` (the to-do list): a note with a take adds a line `take: 4.2 s (asset 39bb…)`.
- **`takes [--out DIR]`** (new): for every open note with a take, in the saved export, prints the `Artifact`
  `read` calls that download them (`url` = the room, `path` = the asset id, `out_dir` =
  `.cut-review/takes/raw`), as JSON the session can run one by one. Run again after downloading, it converts
  each file with ffmpeg to `DIR/<cut>_line<n>_<note id>.wav` (default DIR `.cut-review/takes`): 24 kHz, mono,
  16-bit, loudness evened out (`loudnorm`, −20 LUFS) and leading/trailing silence trimmed; and writes
  `DIR/takes.json`:

  ```json
  [{"note": "…", "cut": "poll", "line": 3, "from": 12.4, "to": 15.9,
    "text": "the whole spoken line", "words": "the words the note is on, or the whole line",
    "wav": "poll_line4_….wav", "seconds": 4.2, "noteText": "…"}]
  ```

  `text` and `words` use the same spoken text and `quote_span` the to-do list uses. A take whose file is
  missing is listed with the `read` call still to run; nothing is invented.
- `fix` is unchanged: re-recording the line and swapping the cut is still what fixes the note.

## Skill (`review-room`)

New section "Notes with a voice take": export notes, `cut-review takes`, run the printed `Artifact` reads, run
`cut-review takes` again, then give each WAV and its `words` to the project's voice step as the reference for
how the line should sound (the persona's voice stays the persona's). Rules: a take is the owner's voice, used only
as a reference for that line; never publish, share or train on it; never copy takes into the repo.

## Where it lives

- Page: `src/cut_review/page/review-room.html` (note form, notes list, script panel; `audioOnly` and the mp4
  writer as one section). Stays generic.
- CLI: `notes.py` (`take` in the to-do, takes listing and `takes.json`), `cli.py` (`takes`), and a small
  `takes.py` for the ffmpeg conversion if `notes.py` would grow past one concern.
- Docs: `docs/spec.md` (the record field, the command, the page behaviour), the skill, and this file.

## Testing

- Unit (pytest): to-do line for a take; `takes` prints a read call per open take and none for resolved notes or
  notes without one; conversion with a generated mp4 (ffmpeg makes one) gives 24 kHz mono WAV with sound;
  `takes.json` fields, including `words` for a span note and a note whose words left the line; missing file.
  Regression tests mutation-checked, as the repo's rule says.
- Page (harness, `tests/harness/`): the mp4 writer on an iPhone-style `.MOV` (HEVC + AAC, made with ffmpeg) and on
  an `.m4a`, the Web Audio fallback on an `.ogg`, refusal of a `.3gp`; the output plays in the harness and ffprobe
  reads it as a plain AAC mp4 (no `moof`). Desktop and 375 px, light and dark.
- Phone, once: a real note with a take in a real room, in the Claude iOS app: record, play back in the form,
  save, play back in the saved note, export with the CLI.

## Out of scope

Live recording in the page (not possible), editing or trimming takes in the room, takes on notes that are not on
a script line, several takes per note, and anything that turns a take into the persona's voice.
