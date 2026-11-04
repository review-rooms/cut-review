"""Profile the review page in the harness, headless: per scenario, layouts and style recalcs (and their time),
script time, long tasks, slow input events, DOM nodes added, frame times and how many distinct playhead
positions were drawn while playing.

    uv run --with playwright python tests/harness/profile_page.py http://127.0.0.1:8775/#teaser <label> [width height]

Prints one JSON line per scenario and writes them to perf-<label>.json in the current folder. Run the same
scenarios against the old and the new page (two harnesses on two ports) to compare; numbers on a busy machine
vary, so compare counts first and run each side more than once. Uses the installed Google Chrome, headless (set
CUT_REVIEW_BROWSER= for Playwright's Chromium).
"""
import os
import json, sys, time
from playwright.sync_api import sync_playwright

URL, LABEL = sys.argv[1], sys.argv[2]
W, H = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (1440, 900)

INIT = r"""
window.__perf = { long: [], events: [], frames: [], added: 0, sampling: false, heads: new Set() };
try { new PerformanceObserver((l) => l.getEntries().forEach((e) => __perf.long.push(e.duration))).observe({ type: "longtask", buffered: true }); } catch (e) {}
try { new PerformanceObserver((l) => l.getEntries().forEach((e) => __perf.events.push([e.name, e.duration, e.processingEnd - e.processingStart, e.processingStart - e.startTime]))).observe({ type: "event", durationThreshold: 16, buffered: true }); } catch (e) {}
let last = 0;
const loop = (t) => { if (__perf.sampling) { if (last) __perf.frames.push(t - last); last = t;
  const ph = document.getElementById("playhead"); if (ph) __perf.heads.add(getComputedStyle(ph).transform + getComputedStyle(ph).left); } else last = 0; requestAnimationFrame(loop); };
requestAnimationFrame(loop);
document.addEventListener("DOMContentLoaded", () => new MutationObserver((ms) => ms.forEach((m) => __perf.added += m.addedNodes.length)).observe(document.body, { childList: true, subtree: true }));
"""

KEYS = ["LayoutCount", "RecalcStyleCount", "LayoutDuration", "RecalcStyleDuration", "ScriptDuration", "TaskDuration"]


def main():
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel=os.environ.get("CUT_REVIEW_BROWSER", "chrome") or None, args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"])
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.add_init_script(INIT)
        cdp = pg.context.new_cdp_session(pg)
        cdp.send("Performance.enable")
        pg.goto(URL)
        pg.wait_for_function("document.getElementById('vid') && document.getElementById('vid').readyState >= 1", timeout=60000)
        pg.wait_for_timeout(800)

        def m():
            r = {x["name"]: x["value"] for x in cdp.send("Performance.getMetrics")["metrics"]}
            return {k: r.get(k, 0) for k in KEYS}

        def run(name, fn, sample=False):
            pg.evaluate("__perf.long=[];__perf.events=[];__perf.frames=[];__perf.added=0;__perf.heads=new Set();__perf.sampling=%s" % ("true" if sample else "false"))
            a = m(); t0 = time.time()
            fn()
            wall = time.time() - t0
            z = m()
            d = {k: round(z[k] - a[k], 3 if "Duration" in k else 0) for k in KEYS}
            for k in KEYS:
                if "Duration" in k: d[k] = round(d[k] * 1000, 1)  # ms
            got = pg.evaluate("({long: __perf.long, events: __perf.events, frames: __perf.frames, added: __perf.added, heads: __perf.heads.size})")
            pg.evaluate("__perf.sampling=false")
            fr = sorted(got["frames"])
            d.update(wall_s=round(wall, 2), long_tasks=len(got["long"]), long_ms=round(sum(got["long"])), nodes_added=got["added"])
            if fr:
                d.update(frames=len(fr), frame_p50=round(fr[len(fr) // 2], 1), frame_p95=round(fr[int(len(fr) * .95)], 1), frames_over_33=sum(f > 33.4 for f in fr))
            if sample: d["playhead_positions"] = got["heads"]
            ev = got["events"]
            if ev:
                d.update(input_events_over16=len(ev), worst_input_ms=round(max(e[1] for e in ev)), worst_processing_ms=round(max(e[2] for e in ev), 1))
            out[name] = d
            print(name, json.dumps(d), flush=True)

        vid = pg.locator("#vid")

        def play():
            pg.evaluate("document.getElementById('vid').currentTime = 0; document.getElementById('vid').muted = true; document.getElementById('vid').play()")
            pg.wait_for_timeout(4000)
            pg.evaluate("document.getElementById('vid').pause()")
        run("playback_4s", play, sample=True)

        def scrub():
            pg.locator("#track").scroll_into_view_if_needed(); pg.wait_for_timeout(200)
            bb = pg.locator("#track").bounding_box()
            y = bb["y"] + bb["height"] / 2
            pg.mouse.move(bb["x"] + 4, y); pg.mouse.down()
            for i in range(80):
                pg.mouse.move(bb["x"] + 4 + (bb["width"] - 8) * i / 79, y)
            pg.mouse.up()
        run("scrub_80_moves", scrub)

        def draw():
            pg.evaluate("document.getElementById('vid').pause()")
            vid.scroll_into_view_if_needed(); pg.wait_for_timeout(200)
            bb = vid.bounding_box()
            x0, y0 = bb["x"] + bb["width"] * .2, bb["y"] + bb["height"] * .2
            pg.mouse.move(x0, y0); pg.mouse.down()
            for i in range(80):
                pg.mouse.move(x0 + bb["width"] * .5 * i / 79, y0 + bb["height"] * .4 * i / 79)
            pg.mouse.up()
        run("draw_region_80_moves", draw)

        def typing():
            pg.locator("#noteText").click()
            pg.keyboard.type("The logo should land a beat later, and the type is too small on phones.", delay=8)
        run("type_72_chars", typing)
        pg.locator("#noteText").fill("")

        def storm():
            pg.evaluate("""async () => { for (let i = 0; i < 25; i++) {
              await window.__db.collection('notes').add({cut: 'teaser', text: 'Note ' + i + ' about the pacing here', status: i % 3 ? 'open' : 'fixed',
                t: i * 0.3, tEnd: i % 2 ? i * 0.3 + 0.5 : null, line: i % 3, quote: null, region: i % 4 ? null : {x: .1, y: .1, w: .3, h: .2},
                by: 'u_harness', version: 1, createdAt: new Date().toISOString(), reply: ''});
              await new Promise((r) => setTimeout(r, 40)); } }""")
            pg.wait_for_timeout(500)
        run("write_25_notes", storm)

        def play2():
            pg.evaluate("document.getElementById('vid').currentTime = 0; document.getElementById('vid').play()")
            pg.wait_for_timeout(4000)
            pg.evaluate("document.getElementById('vid').pause()")
        run("playback_4s_with_25_notes", play2, sample=True)

        def one_write():
            pg.evaluate("""async () => { await window.__db.doc('verdicts/teaser').set({state: 'changes', version: 1, at: 'x'}); await new Promise((r) => setTimeout(r, 300)); }""")
        run("one_verdict_write", one_write)
        b.close()
    json.dump(out, open(f"perf-{LABEL}.json", "w"), indent=1)


main()
