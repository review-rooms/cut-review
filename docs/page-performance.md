# Page performance notes

What keeps `review-room.html` smooth, and why. Read this before changing anything that runs per frame, per
pointer move or per database snapshot.

## The pipeline, and what each kind of change costs

A frame goes script → style → layout → paint → composite. Every change pays for its stage and everything after it:

- `transform` and `opacity` on an element with its own layer: composite only. Use them for anything that moves
  every frame (the playhead, the progress fill, the draft region while drawing).
- colours, shadows, `visibility`: style + paint.
- `left`, `width`, `top`, text content, adding or removing nodes: style + layout + paint, for the subtree and
  often its ancestors.

**Layout thrashing** is writing to the DOM and then reading geometry (`getBoundingClientRect`, `offsetLeft`,
`clientWidth`, `scrollTop`) in the same task: the read forces a synchronous layout, and a loop of write/read
pairs forces one per pair. Read first, then write, and cache geometry that only changes on resize
(`ResizeObserver` gives it for free).

## Timers versus frames

- `requestAnimationFrame` runs once per displayed frame, just before style and layout, and is paused in
  background tabs. Visual updates belong there; `setTimeout`/`setInterval` drift against the display and
  either waste work or drop frames.
- Input events (`pointermove`, `wheel`) can arrive several times per frame. Store the latest value and apply
  it once in a `requestAnimationFrame` callback ("coalescing").
- `video.timeupdate` fires about four times a second (every 250 ms in Chromium), so a playhead driven by it
  moves in visible steps. `requestVideoFrameCallback` fires once per *presented video frame* with the exact
  `mediaTime`; while the video plays the page uses it (falling back to `requestAnimationFrame`), and stops
  the loop on pause. `seeked`/`pause` still do one update.

## Long tasks and INP

A task over 50 ms is a long task: no input is handled and no frame is drawn while it runs. Interaction to Next
Paint (INP) is the delay from an input to the next frame that shows its result; good is under 200 ms, and a
snappy UI stays well under 100 ms. The usual causes here are rebuilding large DOM subtrees in an event handler
and synchronous layouts. Keep handlers small: update state, schedule a render, return.

## Avoiding full re-renders

The database pushes a full snapshot of a collection whenever any document in it changes (the harness fires
every listener on every write). Rebuilding the whole page on each one costs layout, loses scroll positions,
restarts `<video>` and `<audio>` elements, and drops hover and focus. Instead:

- skip a snapshot whose data is the same as what is already shown;
- render in one batched `requestAnimationFrame` pass, however many snapshots arrive;
- rebuild the script only when its lines change; restyle its word marks otherwise;
- keep note cards and set items keyed by id and reuse a node when its record hasn't changed, so a playing take
  or a looping clip keeps playing.

## CSS containment

- `contain: layout paint` (or `content`) on self-contained boxes (note cards, the script box, the timeline)
  keeps a change inside from re-laying out the page.
- `content-visibility: auto` with `contain-intrinsic-size` skips rendering off-screen note cards and set items
  until they scroll near the viewport. It is cheap and needs no JavaScript; it suits the notes list, which can
  grow to hundreds of cards.

## Listeners

- `passive: true` on `wheel`, `touchmove` and `scroll` listeners tells the browser the page won't cancel the
  scroll, so scrolling never waits on script.
- Listeners that must call `preventDefault` (drawing a region, scrubbing) use `touch-action: none` on the
  element instead, so the browser knows ahead of time.

## Motion

Short (120–200 ms) transitions on `transform`, `opacity` and colours make state changes read as continuous
rather than as jumps. Nothing animates layout properties. `prefers-reduced-motion: reduce` turns transitions
and smooth scrolling off.
