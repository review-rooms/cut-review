"""Storyboards, carousels with captions, and the safe-zone overlay, in the harness, headless.

    python3 tests/harness/serve.py <built copy of examples/launch-cuts> 8777
    uv run --with playwright python tests/harness/check_boards.py http://127.0.0.1:8777/ [width height]

Expects the Launch cuts example as it is now: launch-film-board (the storyboard of launch-film, which has no video
yet), teaser-board (the teaser's), and tiktok-photos (three slides with words, two captions).
"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
W, H = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1440, 900)
ok = []


def check(name, cond):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel=os.environ.get("CUT_REVIEW_BROWSER", "chrome") or None)
    pg = b.new_context(viewport={"width": W, "height": H}).new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    J = pg.evaluate

    # a storyboard before its video: shots with their words and seconds, no video to go to yet
    pg.goto(BASE + "#launch-film-board"); pg.wait_for_function("document.querySelectorAll('#items .item').length === 4")
    check("a storyboard says what it is", J("document.getElementById('meta').textContent").startswith("Storyboard · 4 shots"))
    check("each shot shows its voice-over and seconds", pg.locator("#items .itext").count() == 4
          and "2.5 s" in J("document.querySelector('#items .item .cap').textContent"))
    # a board sheet: numbered panels, the words in labelled fields ("VO: …" under VO, the rest under Action)
    check("panels are numbered on a board sheet", J("document.getElementById('items').classList.contains('board')")
          and J("[...document.querySelectorAll('#items .pnum')].map(b => b.textContent).join()") == "1,2,3,4")
    check("a shot's words sit under VO and Action", J("[...document.querySelectorAll('#items .item')[0].querySelectorAll('.fld')].map(f => f.firstChild.textContent + ':' + f.lastChild.textContent)")
          == ['VO:"What if your notes could answer back?"', "Action:Close-up: a hand writes in a notebook."])
    # the timeline: each shot as wide as its seconds; a tap picks the shot and marks it
    segs = J("[...document.querySelectorAll('#sbTl .seg')].map(s => Math.round(s.getBoundingClientRect().width))")
    check("the timeline has a segment per shot, sized by seconds", len(segs) == 4 and segs[2] > segs[1] and not J("document.getElementById('sbTl').hidden"))
    pg.click("#sbTl .seg:nth-child(3)"); pg.wait_for_timeout(150)
    check("tapping a timeline segment picks that shot", J("document.getElementById('itemSel').value") == "Shot 3"
          and J("document.querySelector('#sbTl .seg[aria-current=\"true\"]')?.dataset.item") == "Shot 3")
    pg.click("#sbTl .seg:nth-child(3)"); pg.wait_for_timeout(100); J("document.getElementById('itemSel').value = ''; document.getElementById('itemSel').dispatchEvent(new Event('change'))")
    board = J("[document.getElementById('b-board').hidden, document.getElementById('b-board').textContent, document.getElementById('b-board').disabled]")
    check("no video yet: said, not a link", board == [False, "No video yet", True])
    # the animatic: the shots one after another for their seconds, words under the picture; keys drive it
    pg.click("#b-anim"); pg.wait_for_timeout(200)
    check("Play animatic opens on shot 1 with its words", not J("document.getElementById('anim').hidden")
          and J("document.getElementById('animPos').textContent").startswith("1 / 4") and "answer back" in J("document.getElementById('animTxt').textContent"))
    t0 = J("performance.now()")
    pg.wait_for_function("document.getElementById('animPos').textContent.startsWith('2 / 4')", timeout=6000)
    check("it moves on after the shot's seconds (2.5 s, 0.2 s of it gone already)", 1800 < J("performance.now()") - t0 < 4500)
    pg.keyboard.press("ArrowRight"); pg.keyboard.press("k"); pg.wait_for_timeout(100)
    check("arrow keys step, k pauses", J("document.getElementById('animPos').textContent").startswith("3 / 4") and J("document.getElementById('animPlay').textContent") == "Play")
    pg.click("#animNote"); pg.wait_for_timeout(200)
    check("Note on this shot closes it and picks the shot", J("document.getElementById('anim').hidden") and J("document.getElementById('itemSel').value") == "Shot 3"
          and J("document.activeElement.id") == "noteText")
    pg.keyboard.type("Hold this shot longer"); pg.keyboard.press("Enter")
    pg.wait_for_function("Object.values(window.__store.notes).some((n) => n.text === 'Hold this shot longer')")
    n = [x for x in J("Object.values(window.__store.notes)") if x["text"] == "Hold this shot longer"]
    check("a note on a shot is a note on that item of the storyboard", len(n) == 1 and n[0]["cut"] == "launch-film-board" and n[0]["item"] == "Shot 3")
    # a box on a shot, like on any still
    pg.locator("#items .item").nth(0).locator("img").scroll_into_view_if_needed()
    pg.wait_for_timeout(200)   # a slide scrolled into view is drawn on the next frame (content-visibility)
    ib = pg.locator("#items .item").nth(0).locator("img").bounding_box()
    pg.mouse.move(ib["x"] + ib["width"] * .3, ib["y"] + ib["height"] * .3); pg.mouse.down()
    for i in range(8): pg.mouse.move(ib["x"] + ib["width"] * (.3 + .3 * i / 7), ib["y"] + ib["height"] * (.3 + .2 * i / 7))
    pg.mouse.up(); pg.wait_for_timeout(300)
    drawn = [pg.locator("#items .box.draft").count(), J("document.getElementById('itemSel').value")]
    check(f"a box can be drawn on a shot ({drawn})", drawn == [1, "Shot 1"])
    pg.keyboard.press("Escape")

    # a cut and its storyboard link to each other
    pg.goto(BASE + "#teaser-board"); pg.wait_for_function("document.getElementById('b-board').textContent !== ''")
    check("a storyboard links to its video", J("document.getElementById('b-board').textContent") == "Video →")
    pg.click("#b-board"); pg.wait_for_function("location.hash === '#teaser'")
    check("…which opens the cut", J("location.hash") == "#teaser" and J("document.getElementById('b-board').textContent") == "Storyboard")
    pg.click("#b-board"); pg.wait_for_function("location.hash === '#teaser-board'")
    check("…and the cut links back", J("location.hash") == "#teaser-board")

    # a carousel: slides with their words, then each caption as an item to comment on
    pg.goto(BASE + "#tiktok-photos"); pg.wait_for_function("document.querySelectorAll('#items .textitem').length === 2")
    check("a carousel says its slides, captions and platform", J("document.getElementById('meta').textContent").startswith("3 slides · 2 captions · TikTok"))
    caps = pg.locator("#items .textitem")
    check("each caption is its own item, its words shown", caps.count() == 2 and "notebook finally listens" in caps.nth(0).text_content())
    caps.nth(1).click(); pg.wait_for_timeout(200)
    check("tapping a caption picks it, with no box to draw", J("document.getElementById('itemSel').value") == "Caption B" and J("document.getElementById('b-region').hidden"))
    pg.locator("#noteText").fill("Too long for the first line"); pg.keyboard.press("Enter")
    pg.wait_for_function("Object.values(window.__store.notes).some((n) => n.text === 'Too long for the first line')")
    n = [x for x in J("Object.values(window.__store.notes)") if x["text"] == "Too long for the first line"]
    check("a note on a caption is a note on that item", len(n) == 1 and n[0]["item"] == "Caption B" and n[0]["region"] is None)

    # safe zones: off until picked, on every slide and on the cut, remembered, and off again
    check("safe zones are off by default", pg.locator(".ov").count() == 0 and J("document.getElementById('ovUiL').hidden"))
    pg.select_option("#ovSel", "tiktokphoto"); pg.wait_for_function("document.querySelectorAll('#items .ov').length === 3")
    check("picking a platform draws it on every slide (not the captions)", pg.locator("#items .ov").count() == 3 and pg.locator("#items .ov .unsafe").count() > 0
          and pg.locator("#items .ov circle").count() > 0)
    ov = J("(() => { const o = document.querySelector('#items .ov').getBoundingClientRect(), i = document.querySelector('#items .item img').getBoundingClientRect(); return [o.left - i.left, o.top - i.top, o.width - i.width, o.height - i.height].map(Math.round); })()")
    check(f"the overlay sits exactly on the picture ({ov})", all(abs(v) <= 1 for v in ov))
    pg.uncheck("#ovUi"); pg.wait_for_timeout(200)
    check("Buttons off leaves only the zones", pg.locator("#items .ov circle").count() == 0 and pg.locator("#items .ov .unsafe").count() > 0)
    pg.goto(BASE + "#teaser"); pg.wait_for_function("document.getElementById('vid').readyState >= 1", timeout=30000); pg.wait_for_timeout(400)
    check("the choice is remembered and drawn on the cut", J("document.getElementById('ovSel').value") == "tiktokphoto" and pg.locator("#stage .ov").count() == 1)
    pg.select_option("#ovSel", "reels"); pg.check("#ovUi"); pg.wait_for_timeout(200)
    vb = pg.locator("#vid").bounding_box()
    pg.mouse.click(vb["x"] + vb["width"] * .5, vb["y"] + vb["height"] * .4); pg.wait_for_timeout(200)
    check("the overlay never takes a click (the picture still gets it)", J("getComputedStyle(document.querySelector('#stage .ov')).pointerEvents") == "none")
    pg.select_option("#ovSel", ""); pg.wait_for_timeout(200)
    check("off removes them", pg.locator(".ov").count() == 0)

    # the post preview: each platform's app on a phone; a swipe or the arrows pick the slide shown, notes and boxes go on it
    pg.goto(BASE + "#carousel"); pg.wait_for_function("document.querySelectorAll('#items .item').length > 0")
    check("a carousel offers Slides and Post preview, slides first", not J("document.getElementById('pvBar').hidden")
          and J("document.getElementById('b-grid').getAttribute('aria-pressed')") == "true" and J("document.getElementById('pvWrap').hidden"))
    pg.click("#b-pv"); pg.wait_for_function("document.querySelectorAll('#pv .pvslide').length === 4")
    check("Instagram: the post with its handle, counter and caption", J("document.getElementById('pv').className") == "phone ig"
          and J("document.querySelector('#pv .pvhead b').textContent") == "notebook.app" and J("document.querySelector('#pv .pvcount').textContent") == "1/4"
          and J("document.querySelector('#pv .pvcap').textContent").startswith("notebook.app Your notes") and J("document.getElementById('items').hidden"))
    pg.click("#pv .pvarrow.r"); pg.wait_for_function("document.getElementById('itemSel').value === '02-product'", timeout=4000)
    check("the arrow moves to the next slide and picks it", J("document.querySelector('#pv .pvcount').textContent") == "2/4")
    pg.evaluate("(() => { const t = document.querySelector('#pv .pvtrack'); t.scrollTo({ left: t.clientWidth * 2, behavior: 'instant' }); })()")
    pg.wait_for_function("document.getElementById('itemSel').value === '03-date'", timeout=4000)
    check("a swipe picks the slide it settles on", J("document.querySelector('#pv .pvcount').textContent") == "3/4")
    ib = pg.locator("#pv .pvslide").nth(2).bounding_box()
    pg.mouse.move(ib["x"] + ib["width"] * .3, ib["y"] + ib["height"] * .3); pg.mouse.down()
    for i in range(8): pg.mouse.move(ib["x"] + ib["width"] * (.3 + .3 * i / 7), ib["y"] + ib["height"] * (.3 + .2 * i / 7))
    pg.mouse.up(); pg.wait_for_timeout(300)
    check("a box can be drawn on the slide in the preview", pg.locator("#pv .pvslide").nth(2).locator(".box.draft").count() == 1)
    pg.locator("#noteText").fill("Crop is too tight here"); pg.keyboard.press("Enter")
    pg.wait_for_function("Object.values(window.__store.notes).some((n) => n.text === 'Crop is too tight here')")
    n = [x for x in J("Object.values(window.__store.notes)") if x["text"] == "Crop is too tight here"]
    check("…and the note is on that slide with its box", len(n) == 1 and n[0]["item"] == "03-date" and n[0]["region"] is not None)
    pg.wait_for_timeout(200)
    check("…which then shows on the preview", pg.locator("#pv .pvslide").nth(2).locator(".box.open").count() == 1)
    pg.click("#pv .pvcap"); pg.wait_for_timeout(200)
    check("tapping the caption picks it", J("document.getElementById('itemSel').value") == "Caption" and J("document.querySelector('#pv .pvcap').classList.contains('picked')"))
    pg.goto(BASE + "#tiktok-photos"); pg.wait_for_function("document.querySelectorAll('#pv .pvslide').length === 3")
    check("TikTok: remembered, the For You feed with the slide's words over the photo", J("document.getElementById('pv').className") == "phone tt"
          and "Your notes, but they answer back" in J("document.querySelector('#pv .tttext').textContent") and pg.locator("#pv .ttrail svg").count() == 4)
    pg.locator("#pvCaps button").nth(1).click(); pg.wait_for_timeout(200)
    check("with two captions, a chip shows and picks each", not J("document.getElementById('pvCaps').hidden") and J("document.getElementById('itemSel').value") == "Caption B"
          and J("document.querySelector('#pv .pvcap').textContent").startswith(J("window.__store.sets['tiktok-photos'].items.find((i) => i.name === 'Caption B').text")[:20]) and J("document.querySelectorAll('#pvCaps [aria-pressed=true]').length") == 1)
    pg.goto(BASE + "#youtube-post"); pg.wait_for_function("document.querySelectorAll('#pv .pvslide').length === 3")
    check("YouTube: a post with its text above the images", J("document.getElementById('pv').className") == "phone yt"
          and J("document.querySelector('#pv .pvhead b').textContent") == "@notebook.app"
          and J("document.querySelector('#pv .pvcap').compareDocumentPosition(document.querySelector('#pv .pvmedia')) & 4") == 4)
    ph = J("(() => { const r = document.getElementById('pv').getBoundingClientRect(); return [r.left, r.right, document.documentElement.scrollWidth, innerWidth]; })()")
    check(f"the phone fits the page with no sideways scroll ({ph})", ph[0] >= 0 and ph[1] <= ph[3] and ph[2] <= ph[3])
    pg.click("#b-grid"); pg.wait_for_timeout(200)
    check("Slides goes back to the grid", not J("document.getElementById('items').hidden") and J("document.getElementById('pvWrap').hidden") and pg.locator("#pv .pvslide").count() == 0)

    check(f"no page errors ({errs[:2]})", not errs)
    b.close()

print(f"{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
