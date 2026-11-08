"""Drive the review page's main flows in the harness, headless, and check what they do.

    python3 tests/harness/serve.py examples/launch-cuts 8775      # a built room (see examples/launch-cuts/README.md)
    uv run --with playwright python tests/harness/check_page.py http://127.0.0.1:8775/ [width height]

Uses the installed Google Chrome, headless (Playwright's own Chromium can't play H.264); set CUT_REVIEW_BROWSER=
to use Playwright's Chromium. Expects the Launch cuts example (teaser, explainer, carousel). The issue numbers are
review-rooms/cut-review issues the checks cover.
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
    b = p.chromium.launch(headless=True, channel=os.environ.get("CUT_REVIEW_BROWSER", "chrome") or None, args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"])
    ctx = b.new_context(viewport={"width": W, "height": H})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    J = pg.evaluate
    store = lambda c: J(f"Object.values(window.__store.{c})")

    # 4: a set's hash on a cold load
    pg.goto(BASE + "#carousel"); pg.wait_for_timeout(1500)
    check("#4 cold load on #carousel shows the set", not J("document.getElementById('setView').hidden") and J("document.getElementById('title').textContent") == "Carousel")
    # 6: tap a picture to pick it; whole set by default
    check("#6 nothing picked: Whole set", J("document.getElementById('itemSel').value") == "")
    pg.locator(".item img").nth(1).click(); pg.wait_for_timeout(200)
    check("#6 tapping a picture picks it", J("document.getElementById('itemSel').value") == "02-product" and pg.locator('.item[aria-current="true"]').count() == 1)
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(100)
    check("#6 arrow keys move", J("document.getElementById('itemSel').value") == "03-date")
    # 11: the clip keeps its place when a note is added
    J("(() => { const v = document.querySelector('.item video'); v.pause(); v.currentTime = 2; })()"); pg.wait_for_timeout(500)
    clip = J("document.querySelector('.item video')")
    J("window.__clip = document.querySelector('.item video')")
    pg.locator("#noteText").fill("Date is hard to read"); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["cut"] == "carousel"]
    check("set note saved on the picked item", len(n) == 1 and n[0]["item"] == "03-date")
    check("#11 clip element kept, still at 2 s and paused", J("window.__clip === document.querySelector('.item video') && window.__clip.paused && Math.abs(window.__clip.currentTime - 2) < 0.1"))
    pg.locator(".item img").nth(2).click(); pg.wait_for_timeout(100)
    check("#6 tapping the picked item again unpicks it", J("document.getElementById('itemSel').value") == "")
    # 17: a box on a still saves the region with its item; unpicking (whole set) drops it and the Box button
    im = pg.locator(".item img").nth(0); im.scroll_into_view_if_needed(); ib = im.bounding_box()
    pg.mouse.move(ib["x"] + ib["width"] * .2, ib["y"] + ib["height"] * .2); pg.mouse.down()
    for i in range(12): pg.mouse.move(ib["x"] + ib["width"] * (.2 + .4 * i / 11), ib["y"] + ib["height"] * (.2 + .3 * i / 11))
    pg.mouse.up(); pg.wait_for_timeout(300)
    check("dragging on a still picks it and keeps the box", J("document.getElementById('itemSel').value") == "01-question"
          and pg.locator('.item[data-item="01-question"] .box.draft').count() == 1)
    pg.locator("#noteText").fill("Crop tighter"); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["cut"] == "carousel" and x.get("region")]
    check("set note saved with region and item", len(n) == 1 and n[0]["item"] == "01-question" and n[0]["region"]["w"] > .3)
    pg.locator(".item img").nth(0).click(); pg.wait_for_timeout(100)   # picked: unpick
    check("whole set: no Box button", J("document.getElementById('itemSel').value") == "" and J("document.getElementById('b-region').hidden"))
    pg.locator("#noteText").fill("All a bit dark"); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["cut"] == "carousel" and x["text"] == "All a bit dark"]
    check("whole-set note has item null", len(n) == 1 and n[0]["item"] is None and n[0]["region"] is None)
    pg.locator(".item img").nth(0).scroll_into_view_if_needed(); ib = pg.locator(".item img").nth(0).bounding_box()
    pg.mouse.move(ib["x"] + ib["width"] * .2, ib["y"] + ib["height"] * .2); pg.mouse.down()
    for i in range(12): pg.mouse.move(ib["x"] + ib["width"] * (.2 + .4 * i / 11), ib["y"] + ib["height"] * (.2 + .3 * i / 11))
    pg.mouse.up(); pg.wait_for_timeout(600)
    J("document.activeElement.blur()"); pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(100)   # another item, with an unsaved box
    check("picking another item drops the unsaved box (" + J("document.getElementById('itemSel').value") + ")", J("document.getElementById('itemSel').value") == "02-product" and pg.locator(".item .box.draft").count() == 0)
    pg.locator(".item img").nth(1).click(); pg.wait_for_timeout(100)   # and unpick
    check("tapping it again: whole set", J("document.getElementById('itemSel').value") == "")
    pg.locator("#noteText").fill("")
    # 13: a picked clip item takes a time or range from its own video; the note seeks that clip
    clipName = J("document.querySelector('.item video').closest('.item').dataset.item")
    C = f"document.querySelector('.item[data-item=\"{clipName}\"] video')"
    seekClip = lambda t: J(f"(async () => {{ const v = {C}; v.pause(); v.currentTime = {t}; await new Promise(r => v.addEventListener('seeked', r, {{once: true}})); }})()")
    check("#13 whole set: no From/To", J("document.getElementById('timeRow').hidden"))
    pg.locator(f'.item[data-item="{clipName}"] .cap .mono').click(); pg.wait_for_timeout(200)
    seekClip(1); pg.wait_for_timeout(200)
    check("#13 picked clip: From follows it", not J("document.getElementById('timeRow').hidden") and J("document.getElementById('tFrom').value") == "0:01.0")
    pg.locator("#b-restamp").click(); seekClip(2); pg.locator("#b-end").click(); pg.wait_for_timeout(100)
    pg.locator("#noteText").fill("Clip cuts too early"); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["text"] == "Clip cuts too early"]
    check("#13 range note on the clip", len(n) == 1 and n[0]["item"] == clipName and n[0]["t"] == 1 and n[0]["tEnd"] == 2)
    seekClip(0); lbl = pg.locator(".note .top .t").filter(has_text=clipName + " · 0:01.0–0:02.0")
    lbl.click(); pg.wait_for_timeout(300)
    check("#13 the note's time seeks its clip", lbl.count() == 1 and abs(J(f"{C}.currentTime") - 1) < 0.05)
    J("document.activeElement.blur()"); pg.locator(f'.item[data-item="{clipName}"] .cap .mono').click(); pg.wait_for_timeout(100)
    check("#13 unpicked: whole set again", J("document.getElementById('itemSel').value") == "" and J("document.getElementById('timeRow').hidden"))
    # 9: unknown hash on a hash change
    J("location.hash = '#nonexistent'"); pg.wait_for_timeout(300)
    check("#9 unknown hash: corrected and explained", J("location.hash") == "#carousel" and "nonexistent" in J("document.getElementById('status').textContent"))
    pg.locator(".cutbtn").first.click(); pg.wait_for_timeout(500)
    check("#9 notice goes when a cut is picked", J("document.getElementById('status').hidden"))

    # cut: playback moves the playhead every frame
    pg.wait_for_function("document.getElementById('vid').readyState >= 2", timeout=30000)
    J("(() => { const v = document.getElementById('vid'); v.muted = true; v.currentTime = 0; v.play(); })()")
    pg.wait_for_timeout(1500)
    tf = J("getComputedStyle(document.getElementById('playhead')).transform")
    J("document.getElementById('vid').pause()"); pg.wait_for_timeout(300)
    check("playhead moved by transform while playing", tf not in ("none", "matrix(1, 0, 0, 1, 0, 0)"))
    check("script line lit while playing", pg.locator("#script .sline.now").count() == 1)
    check("time and '/ length · f frame' shown", J("document.getElementById('tc').textContent").startswith("0:0") and " · f " in J("document.getElementById('fr').textContent"))
    # the timeline scrubs (paused while held, playing again after), and never touches the note's time
    pg.locator("#track").scroll_into_view_if_needed()
    bb = pg.locator("#track").bounding_box(); y = bb["y"] + bb["height"] / 2
    lb = pg.locator("#lane").bounding_box()
    check(f"the notes lane sits right above the timeline, as wide ({lb})", abs(lb["y"] + lb["height"] - bb["y"]) < 1.5
          and abs(lb["x"] - bb["x"]) < 1 and abs(lb["width"] - bb["width"]) < 1 and J("document.getElementById('lane').getAttribute('aria-label')"))
    check("the lane shows it's there: a tinted band with a note icon", (J("getComputedStyle(document.getElementById('lane')).backgroundColor") not in ("rgba(0, 0, 0, 0)", "transparent") or J("getComputedStyle(document.getElementById('lane')).backgroundImage") != "none")
          and J("getComputedStyle(document.getElementById('lane'), '::before').content") not in ("none", "normal"))
    if W <= 760:
        check("phone: the lane and timeline span the transport, first", J("document.querySelector('.tl').getBoundingClientRect().width") >= J("document.querySelector('.controls').getBoundingClientRect().width") - 1
              and lb["y"] < pg.locator("#b-play").bounding_box()["y"])
    check("no horizontal scroll", J("document.documentElement.scrollWidth <= window.innerWidth"))
    # any screen shape: the picture and the timeline under it fit on the screen together, and the timeline is long
    # enough to scrub (its own row when the player is narrow)
    fit = J("""(() => { const v = document.getElementById('vid').getBoundingClientRect(), t = document.getElementById('track').getBoundingClientRect();
      return { span: Math.round(t.bottom - v.top), tw: Math.round(t.width), vh: Math.round(v.height) }; })()""")
    check(f"player fits the screen ({fit['span']} of {H} px), timeline {fit['tw']} px", fit["span"] <= H and fit["vh"] >= 150 and fit["tw"] >= min(300, W - 40))
    with pg.expect_download(timeout=15000) as dl:   # the stand-in saves the file for real, as claude.ai would
        pg.locator("#b-dl").click()
    check(f"Download saves the video ({dl.value.suggested_filename})", dl.value.suggested_filename.endswith(".mp4") and len(J("window.__downloads")) == 1)
    # with nothing stamped yet, From follows the playhead, so it follows a scrub too (and nothing gets stamped)
    pg.locator("#track").scroll_into_view_if_needed(); bb = pg.locator("#track").bounding_box(); y = bb["y"] + bb["height"] / 2
    pg.mouse.move(bb["x"] + bb["width"] * .1, y); pg.mouse.down()
    for i in range(10): pg.mouse.move(bb["x"] + bb["width"] * (.1 + .4 * i / 9), y)
    pg.mouse.up(); pg.wait_for_timeout(300)
    check("an unstamped From follows a scrub, no range", J("document.getElementById('tFrom').value").startswith("0:04") and J("document.getElementById('tTo').value") == "")
    J("document.getElementById('vid').play()"); pg.wait_for_timeout(300)
    pg.locator("#lane").scroll_into_view_if_needed(); lb = pg.locator("#lane").bounding_box()
    pg.mouse.click(lb["x"] + lb["width"] * .6, lb["y"] + lb["height"] / 2); pg.wait_for_timeout(400)
    check("a click on empty lane seeks and keeps playing, like the timeline", not J("document.getElementById('vid').paused")
          and .6 <= J("document.getElementById('vid').currentTime / document.getElementById('vid').duration") < .75)
    J("document.getElementById('vid').pause()"); pg.wait_for_timeout(200)
    pg.locator("#b-restamp").click(); pg.wait_for_timeout(100)
    fr0 = J("document.getElementById('tFrom').value")
    J("document.getElementById('vid').play()"); pg.wait_for_timeout(300)
    pg.locator("#track").scroll_into_view_if_needed(); bb = pg.locator("#track").bounding_box(); y = bb["y"] + bb["height"] / 2
    pg.mouse.move(bb["x"] + bb["width"] * .25, y); pg.mouse.down()
    for i in range(20): pg.mouse.move(bb["x"] + bb["width"] * (.25 + .5 * i / 19), y); pg.wait_for_timeout(15)
    pg.wait_for_timeout(300)
    mid, held = J("[document.getElementById('vid').currentTime / document.getElementById('vid').duration, document.getElementById('vid').paused]")
    pg.mouse.up(); pg.wait_for_timeout(300)
    check(f"dragging the timeline scrubs, paused while held ({mid:.2f})", abs(mid - .75) < .03 and held)
    check("and plays on after the release, as it was", not J("document.getElementById('vid').paused"))
    J("document.getElementById('vid').pause()"); pg.wait_for_timeout(200)
    check(f"scrubbing leaves the note's time alone ({fr0})", J("document.getElementById('tFrom').value") == fr0 and J("document.getElementById('tTo').value") == ""
          and pg.locator("#lane .sel").count() == 0)
    # the lane marks a range
    pg.locator("#lane").scroll_into_view_if_needed(); lb = pg.locator("#lane").bounding_box(); ly = lb["y"] + lb["height"] / 2
    pg.mouse.move(lb["x"] + lb["width"] * .25, ly); pg.mouse.down()
    for i in range(20): pg.mouse.move(lb["x"] + lb["width"] * (.25 + .25 * i / 19), ly)
    pg.mouse.up(); pg.wait_for_timeout(400)
    fr, to = J("[document.getElementById('tFrom').value, document.getElementById('tTo').value]")
    check(f"dragging the lane marks a range ({fr}–{to})", fr.startswith("0:02") and to.startswith("0:04") and pg.locator("#lane .sel").count() == 1)
    # 7: an invalid time blocks Add and says why
    pg.locator("#noteText").fill("Hold the logo")
    pg.locator("#tFrom").fill("abc"); pg.keyboard.press("Tab"); pg.wait_for_timeout(100)
    check("#7 invalid From flagged, Add disabled, hint says why", J("document.getElementById('tFrom').getAttribute('aria-invalid')") == "true"
          and J("document.getElementById('b-add').disabled") and "isn't a time" in J("document.getElementById('composerHint').textContent"))
    before = len(store("notes"))
    pg.locator("#noteText").focus(); pg.keyboard.press("Enter"); pg.wait_for_timeout(300)
    check("#7 Enter doesn't save with a bad time", len(store("notes")) == before)
    pg.locator("#tFrom").fill("1.5"); pg.keyboard.press("Enter"); pg.wait_for_timeout(100)
    check("#7 a valid time clears the flag", not J("document.getElementById('tFrom').hasAttribute('aria-invalid')") and not J("document.getElementById('b-add').disabled"))
    # region drawn on the picture, then the note
    pg.locator("#vid").scroll_into_view_if_needed()
    vb = pg.locator("#vid").bounding_box()
    pg.mouse.move(vb["x"] + vb["width"] * .3, vb["y"] + vb["height"] * .3); pg.mouse.down()
    for i in range(15): pg.mouse.move(vb["x"] + vb["width"] * (.3 + .3 * i / 14), vb["y"] + vb["height"] * (.3 + .2 * i / 14))
    pg.mouse.up(); pg.wait_for_timeout(300)
    cb, bb = pg.locator("#composer").bounding_box(), pg.locator("#regions .box.draft").bounding_box()
    check("a new box floats the note form next to it, focused", J("document.getElementById('composer').classList.contains('onbox')")
          and J("document.activeElement.id") == "noteText" and J("document.getElementById('lineTargetN').textContent") == "Box ·"
          and abs(cb["x"] - max(8, min(bb["x"], W - cb["width"] - 8))) < 2 and (cb["y"] >= bb["y"] + bb["height"] - 1 or cb["y"] + cb["height"] <= bb["y"] + 1 or abs(cb["y"] + cb["height"] - (H - 8)) < 2)
          and cb["x"] >= 0 and cb["x"] + cb["width"] <= W and cb["y"] >= 0 and cb["y"] + cb["height"] <= H)
    pg.locator("#b-add").click(); pg.wait_for_timeout(600)
    check("adding puts the form back in the notes panel", J("document.getElementById('composer').parentNode.id") == "dock")
    n = [x for x in store("notes") if x["cut"] == "teaser"]
    check("note saved with range and region", len(n) == 1 and n[0]["t"] == 1.5 and n[0]["tEnd"] is not None and n[0]["region"] and n[0]["region"]["w"] > .2)
    check("note card and timeline mark shown", pg.locator("#notes .note").count() == 1 and pg.locator("#lane .mark").count() == 1)
    J("document.getElementById('vid').currentTime = 6"); pg.wait_for_timeout(300)
    pg.locator("#lane .mark").click(); pg.wait_for_timeout(300)
    check("clicking a mark focuses its note", pg.locator("#notes .note.focus").count() == 1 and abs(J("document.getElementById('vid').currentTime") - 1.5) < 0.05)
    J("document.getElementById('vid').currentTime = 6"); pg.wait_for_timeout(300)
    pg.locator("#lane").click(position={"x": lb["width"] * .9, "y": lb["height"] / 2}); pg.wait_for_timeout(300)
    check("a click on empty lane space seeks there", abs(J("document.getElementById('vid').currentTime / document.getElementById('vid').duration") - .9) < .03)
    # a lane drag saves a note with t and tEnd
    pg.locator("#lane").scroll_into_view_if_needed(); lb = pg.locator("#lane").bounding_box(); ly = lb["y"] + lb["height"] / 2
    pg.mouse.move(lb["x"] + lb["width"] * .6, ly); pg.mouse.down()   # clear of the first note's mark and its hit area
    for i in range(20): pg.mouse.move(lb["x"] + lb["width"] * (.6 + .25 * i / 19), ly)
    pg.mouse.up(); pg.wait_for_timeout(300)
    pg.locator("#noteText").fill("Too long here"); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["text"] == "Too long here"]
    check(f"a lane range saves a note with t and tEnd ({n and (n[0]['t'], n[0]['tEnd'])})", len(n) == 1 and 4.6 < n[0]["t"] < 5 and 6.6 < n[0]["tEnd"] < 7)
    # 8: a cue is spaced from the word before it
    check("#8 cue has a space before it", " pause answer" in J("document.querySelector('#script .sline .say').textContent"))
    # 5: Comment keeps the words picked on the line
    pg.locator("#script .sline").first.locator(".w").nth(5).click(); pg.wait_for_timeout(200)
    check("a word opens the note form under its line", J("document.getElementById('composer').parentNode.id") == "scriptBox"
          and J("document.getElementById('composer').classList.contains('pop')"))
    pg.locator("#script .sline").first.locator(".lbtn").click(); pg.wait_for_timeout(200)
    check("#5 Comment keeps the picked word", J("document.getElementById('lineTargetQ').textContent") == "“answer”")
    pg.locator("#noteText").focus(); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("Esc puts the form back in the notes panel", J("document.getElementById('composer').parentNode.id") == "dock")
    pg.locator("#script .sline").first.locator(".w").nth(5).click(); pg.wait_for_timeout(200)
    pg.locator("#noteText").fill("Say it warmer"); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["cut"] == "teaser" and x.get("line") == 0]
    check("a note on a word saves its line and quote", len(n) == 1 and n[0]["quote"] == "answer" and J("document.getElementById('composer').parentNode.id") == "dock")
    # a box scrolled out of view: the form goes back to the panel rather than float off the page
    if J("document.scrollingElement.scrollHeight > innerHeight + 200"):
        pg.locator("#vid").scroll_into_view_if_needed(); vb = pg.locator("#vid").bounding_box()
        pg.mouse.move(vb["x"] + vb["width"] * .3, vb["y"] + vb["height"] * .1); pg.mouse.down()
        for i in range(10): pg.mouse.move(vb["x"] + vb["width"] * (.3 + .2 * i / 9), vb["y"] + vb["height"] * (.1 + .1 * i / 9))
        pg.mouse.up(); pg.wait_for_timeout(300)
        J("scrollBy(0, document.getElementById('regions').getBoundingClientRect().bottom + 50)"); pg.wait_for_timeout(300)
        check("a box scrolled away docks the form", J("document.getElementById('composer').parentNode.id") == "dock")
        J("scrollTo(0, 0)"); pg.wait_for_timeout(200)
        pg.locator("#noteText").focus(); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    # right-click on the timeline: the form opens there, at that time
    J("document.activeElement.blur()")
    pg.locator("#track").scroll_into_view_if_needed(); tb = pg.locator("#track").bounding_box()
    pg.mouse.click(tb["x"] + tb["width"] * .5, tb["y"] + tb["height"] / 2, button="right"); pg.wait_for_timeout(300)
    cb = pg.locator("#composer").bounding_box()
    check("right-click on the timeline opens the form there, at that time", J("document.getElementById('composer').classList.contains('pop')")
          and J("document.activeElement.id") == "noteText" and J("document.getElementById('lineTargetN').textContent") == "At ·"
          and J("document.getElementById('lineTargetQ').textContent").startswith("0:04") and (abs(cb["y"] - (tb["y"] + tb["height"] + 8)) < 3 or cb["y"] + cb["height"] <= tb["y"] + tb["height"] - 7)
          and abs(J("document.getElementById('vid').currentTime") - 4) < .2)
    pg.keyboard.type("Beat drops here"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    n = [x for x in store("notes") if x["text"] == "Beat drops here"]
    check("the note is at the right-clicked time", len(n) == 1 and 3.8 < n[0]["t"] < 4.2 and n[0]["tEnd"] is None
          and J("document.getElementById('composer').parentNode.id") == "dock")
    J("(() => { const s = window.__store.notes; for (const id in s) if (s[id].text === 'Beat drops here') window.__db.doc('notes/' + id).delete(); })()"); pg.wait_for_timeout(300)   # the steps below count the notes
    # right-click on the picture: the form at the cursor, on this frame; Esc closes it
    J("document.getElementById('vid').currentTime = 1.5"); pg.wait_for_timeout(200)
    pg.locator("#vid").scroll_into_view_if_needed(); vb = pg.locator("#vid").bounding_box()
    pg.mouse.click(vb["x"] + vb["width"] * .5, vb["y"] + vb["height"] * .3, button="right"); pg.wait_for_timeout(300)
    check("right-click on the picture opens the form on this frame", J("document.getElementById('composer').classList.contains('onbox')")
          and J("document.getElementById('lineTargetQ').textContent") == "0:01.5")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("Esc closes it", J("document.getElementById('composer').parentNode.id") == "dock")
    # a left-click elsewhere closes it too
    pg.mouse.click(vb["x"] + vb["width"] * .5, vb["y"] + vb["height"] * .3, button="right"); pg.wait_for_timeout(300)
    pg.locator("#track").scroll_into_view_if_needed(); tb = pg.locator("#track").bounding_box()
    pg.mouse.click(tb["x"] + tb["width"] * .2, tb["y"] + tb["height"] / 2); pg.wait_for_timeout(300)
    check("a left-click elsewhere closes the right-click form", J("document.getElementById('composer').parentNode.id") == "dock"
          and J("document.getElementById('lineTarget').hidden"))
    # Esc on a floating box form drops the box
    pg.locator("#vid").scroll_into_view_if_needed(); vb = pg.locator("#vid").bounding_box()
    pg.mouse.move(vb["x"] + vb["width"] * .5, vb["y"] + vb["height"] * .5); pg.mouse.down()
    for i in range(10): pg.mouse.move(vb["x"] + vb["width"] * (.5 + .2 * i / 9), vb["y"] + vb["height"] * (.5 + .2 * i / 9))
    pg.mouse.up(); pg.wait_for_timeout(300)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("Esc drops the box and the form goes back", J("document.getElementById('composer').parentNode.id") == "dock" and pg.locator("#regions .box.draft").count() == 0)
    # unresolved notes hold Approve back (no Needs changes button any more)
    check("only an Approve button", pg.locator("#approve").count() == 1)
    check("Approve waits for the 3 open notes", J("document.querySelector('#approve').disabled")
          and J("document.getElementById('approveHint').textContent") == "Resolve the 3 unresolved notes to approve."
          and pg.locator('.cutbtn[aria-current="true"] .dot.changes').count() == 1)
    # Ask Claude to apply: one click hands the open notes to the viewer's Claude
    nopen = J("Object.values(window.__store.notes).filter((n) => n.status === 'open').length")
    check(f"Ask Claude to apply shows with the room's {nopen} open notes", pg.locator("#b-apply").is_visible()
          and J("document.getElementById('b-apply').textContent") == f"Ask Claude to apply {nopen} notes")
    pg.locator("#b-apply").click(); pg.wait_for_timeout(200)
    sent = J("window.__sent")
    check(f"it sends the request ({sent and sent[0]['data'].get('request')})", len(sent) == 1 and sent[0]["deliver"] == "send"
          and sent[0]["data"]["request"] == "apply_notes" and sent[0]["data"]["openNotes"] == nopen and "teaser" in sent[0]["data"]["cuts"])
    # editing your own note
    card = pg.locator("#notes .note").filter(has_text="Too long here")
    card.get_by_role("button", name="Edit").click(); pg.wait_for_timeout(200)
    pg.locator("#notes .editbox textarea").fill("Too long, trim a second"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    n = [x for x in store("notes") if x["text"] == "Too long, trim a second"]
    check("Edit rewrites the note in place", len(n) == 1 and n[0].get("editedAt") and n[0]["status"] == "open"
          and pg.locator("#notes .note .body").filter(has_text="Too long, trim a second").count() == 1 and pg.locator("#notes .editbox").count() == 0)
    nid = J("Object.entries(window.__store.notes).find(([, x]) => x.text === 'Too long, trim a second')[0]")
    J(f"window.__db.doc('notes/{nid}').update({{status: 'fixed', reply: 'Trimmed.', fixedIn: 2}})"); pg.wait_for_timeout(400)
    card = pg.locator("#notes .note").filter(has_text="Too long, trim a second")
    card.get_by_role("button", name="Edit").click(); pg.wait_for_timeout(200)
    pg.locator("#notes .editbox textarea").fill("Too long, trim two seconds"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    check("editing a fixed note reopens it", J(f"window.__store.notes['{nid}'].status") == "open")
    # an editor left open doesn't take the cursor back when that note changes
    pg.locator("#notes .note").filter(has_text="Too long, trim two seconds").get_by_role("button", name="Edit").click(); pg.wait_for_timeout(200)
    J("window.__other = document.querySelector('#notes .note:not(:has(.editbox))')")
    pg.locator("#noteText").focus()
    J(f"window.__db.doc('notes/{nid}').update({{reply: 'Seen.'}})"); pg.wait_for_timeout(400)
    check("a live change keeps the cursor where it is, and other cards as they were", J("document.activeElement.id") == "noteText"
          and pg.locator("#notes .editbox").count() == 1 and J("window.__other.isConnected"))
    pg.locator("#notes .editbox").get_by_role("button", name="Cancel").click(); pg.wait_for_timeout(200)
    # replying: a thread under the note, the owner's and Claude's replies in order
    card = pg.locator("#notes .note").filter(has_text="Too long, trim two seconds")
    card.get_by_role("button", name="Reply").click(); pg.wait_for_timeout(200)
    check("Reply opens a box with the cursor in it", J("document.activeElement.closest('.editbox') !== null") and J("document.activeElement.getAttribute('aria-label')") == "Reply to the note")
    pg.keyboard.type("Why two and not one?"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    reps = J("Object.values(window.__store.replies || {})")
    check("the reply is its own document on the note", len(reps) == 1 and reps[0]["note"] == nid and reps[0]["text"] == "Why two and not one?" and reps[0]["cut"] == "teaser")
    J(f"window.__db.doc('replies/{nid}--claude-1').set({{note: '{nid}', cut: 'teaser', by: 'claude', text: 'One second cut the beat.', at: '9998'}})")
    J(f"window.__db.collection('replies').add({{note: '{nid}', cut: 'teaser', by: 'claude', text: 'Typed as Claude.', at: '9999'}})"); pg.wait_for_timeout(400)
    thread = J(f"[...document.querySelector('#notes .note[data-id=\"{nid}\"]').querySelectorAll('.reply')].map((r) => r.textContent)")
    check(f"the thread reads in order ({thread})", thread[-3:] == ["You: Why two and not one?", "Claude: One second cut the beat.", "Reviewer: Typed as Claude."] and pg.locator("#notes .editbox").count() == 0)
    # resolving: unresolved first in time order, the filter splits them
    first = pg.locator("#notes .note").first
    first.get_by_role("button", name="Resolve").click(); pg.wait_for_timeout(400)
    check("Resolve hides it from Unresolved", pg.locator("#notes .note").count() == 2)
    pg.locator('#filter [data-f="all"]').click(); pg.wait_for_timeout(200)
    st = J("[...document.querySelectorAll('#notes .note')].map((c) => c.classList.contains('resolved'))")
    check(f"All: unresolved on top, resolved after ({st})", st == [False, False, True])
    ts = J("[...document.querySelectorAll('#notes .note:not(.resolved)')].map((c) => window.__store.notes[c.dataset.id].t)")
    check(f"unresolved notes in timeline order ({ts})", ts == sorted(ts))
    pg.locator('#filter [data-f="done"]').click(); pg.wait_for_timeout(200)
    check("Resolved shows only resolved notes", pg.locator("#notes .note").count() == 1 and pg.locator("#notes .note.resolved").count() == 1)
    pg.locator('#filter [data-f="active"]').click(); pg.wait_for_timeout(200)
    for _ in range(2): pg.locator("#notes .note").first.get_by_role("button", name="Resolve").click(); pg.wait_for_timeout(400)
    check("every note resolved: Approve is free", not J("document.querySelector('#approve').disabled") and J("document.getElementById('approveHint').hidden"))
    # the verdict toggles: press it again to go back to unreviewed
    pg.locator("#approve").click(); pg.wait_for_timeout(300)
    on = J("window.__store.verdicts.teaser && window.__store.verdicts.teaser.state")
    pg.locator("#approve").click(); pg.wait_for_timeout(300)
    check("Approve toggles on and back off", on == "approved" and J("window.__store.verdicts.teaser.state") == "none")
    nopen = J("Object.values(window.__store.notes).filter((n) => n.status === 'open').length")
    check(f"the button counts what is still open ({nopen})", J("document.getElementById('b-apply').textContent").endswith(f" {nopen} notes") == bool(nopen) and pg.locator("#b-apply").is_visible() == bool(nopen))
    # a note written after the approval undoes it, even once resolved
    pg.locator("#approve").click(); pg.wait_for_timeout(300)
    pg.locator("#noteText").fill("One more thing"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    pg.locator('#filter [data-f="active"]').click(); pg.wait_for_timeout(200)
    pg.locator("#notes .note").first.get_by_role("button", name="Resolve").click(); pg.wait_for_timeout(400)
    check("a later note undoes the approval", J("document.getElementById('approve').getAttribute('aria-pressed')") == "false"
          and pg.locator('.cutbtn[aria-current="true"] .dot.approved').count() == 0 and not J("document.getElementById('approve').disabled"))
    pg.locator('#filter [data-f="all"]').click(); pg.wait_for_timeout(200)
    # a plain click on the picture plays
    J("document.getElementById('vid').pause()"); pg.locator("#vid").click(); pg.wait_for_timeout(300)
    check("clicking the picture plays", not J("document.getElementById('vid').paused")); J("document.getElementById('vid').pause()")
    # a note card is kept across a snapshot that doesn't change it
    J("window.__card = document.querySelector('#notes .note')")
    J("window.__db.doc('verdicts/teaser').set({state: 'approved', version: 1, at: 'x'})"); pg.wait_for_timeout(400)
    check("verdict write keeps note cards", J("window.__card === document.querySelector('#notes .note')"))
    check("verdict shows in the cut list", pg.locator(".cutbtn .dot.approved").count() >= 1)
    check("no page errors", not errs)
    if errs: print(errs)
    ctx.close()

    # nothing beside the room to take a send (a room served locally): no Ask Claude button
    ctx = b.new_context(viewport={"width": W, "height": H}); pg = ctx.new_page(); J = pg.evaluate
    pg.goto(BASE + "?noclaude#teaser"); pg.wait_for_function("document.getElementById('vid').readyState >= 1", timeout=30000)
    J("window.__db.collection('notes').add({cut: 'teaser', text: 'x', status: 'open', t: 1, version: 1, createdAt: 'z'})"); pg.wait_for_timeout(400)
    check("no Claude beside the room: no Ask Claude button", pg.locator("#notes .note").count() == 1 and not pg.locator("#b-apply").is_visible())
    ctx.close()

    # takes with a fake mic (12)
    ctx = b.new_context(viewport={"width": W, "height": H}); pg = ctx.new_page(); J = pg.evaluate
    pg.goto(BASE + "?mic=fake#teaser"); pg.wait_for_function("document.getElementById('vid').readyState >= 1", timeout=30000)
    pg.locator("#script .w").nth(1).click(); pg.wait_for_timeout(300)
    check("take row shows with a mic", J("!document.getElementById('takeRow').hidden"))
    pg.locator("#b-rec").click(); pg.wait_for_timeout(1500); pg.locator("#b-stop").click(); pg.wait_for_timeout(1200)
    check("#12 hint says words are optional with a take", "with a few words if you like" in J("document.getElementById('composerHint').textContent"))
    check("a take alone enables Add", J("!document.getElementById('b-add').disabled"))
    pg.locator("#noteText").fill("Softer"); pg.keyboard.press("Enter"); pg.wait_for_timeout(1500)
    n = list(J("Object.values(window.__store.notes)"))
    check("note with a take saved", len(n) == 1 and n[0]["take"] and n[0]["take"]["seconds"] > 0)
    J("window.__audio = document.querySelector('#notes .note audio')")
    J("window.__db.doc('verdicts/teaser').set({state: 'changes', version: 1, at: 'y'})"); pg.wait_for_timeout(400)
    check("take player survives an unrelated write", J("!!window.__audio && window.__audio === document.querySelector('#notes .note audio')"))
    ctx.close()

    # version history: the explainer at v3, v2 kept (the teaser's video and a one-line script), v1 from before
    # history was kept; a note on each of v2 and v3, and a "Needs changes" given on v2
    ctx = b.new_context(viewport={"width": W, "height": H}); pg = ctx.new_page(); J = pg.evaluate
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "#explainer"); pg.wait_for_function("document.getElementById('vid').readyState >= 1", timeout=30000)
    J("""(async () => {
      const s = window.__store, x = s.cuts.explainer, t = s.cuts.teaser;
      window.__cur = x.video; window.__old = t.video;
      const note = (id, version, status, text, t0) => window.__db.doc('notes/' + id).set({ cut: 'explainer', t: t0, tEnd: null, region: null,
        item: null, line: null, quote: null, qStart: null, qEnd: null, text, status, reply: status === 'resolved' ? 'Done in v3.' : '',
        version, by: 'u_reviewer', createdAt: '2026-11-0' + version + 'T10:00:00Z' });
      await note('old', 2, 'resolved', 'Logo too small', 1);
      await note('new', 3, 'open', 'Music too loud', 2);
      await window.__db.doc('verdicts/explainer').set({ state: 'changes', version: 2, at: 'x' });
      await window.__db.doc('cuts/explainer').set({ ...x, version: 3,
        changes: [{ v: 2, note: 'Bigger logo' }, { v: 3, note: 'Quieter music' }],
        history: [{ v: 2, video: t.video, poster: t.poster, script: [{ from: 0, to: 2, text: 'An older line' }], length: 8, note: 'Bigger logo' }] });
    })()"""); pg.wait_for_timeout(600)
    opts = J("[...document.querySelectorAll('#verSel option')].map((o) => [o.textContent, o.disabled])")
    check(f"version menu lists current, kept and not-kept versions ({opts})", not J("document.getElementById('verSel').hidden")
          and opts == [["v3 · current · Quieter music", False], ["v2 · Bigger logo", False], ["v1 · not kept", True]])
    check("an old Needs changes counts as nothing; the open note holds Approve", J("document.querySelector('#approve').getAttribute('aria-pressed')") == "false"
          and J("document.getElementById('approveHint').textContent") == "Resolve the unresolved note to approve.")
    check("the cut list dot is amber for the open note", J("document.querySelector('.cutbtn[aria-current=\"true\"] .dot').classList.contains('changes')"))
    check("current version: only v3's active note", J("[...document.querySelectorAll('#notes .note .body')].map((b) => b.textContent)") == ["Music too loud"])
    check("current version: the sound switch shows", not J("document.getElementById('versions').hidden"))
    pg.select_option("#verSel", "2"); pg.wait_for_timeout(500)
    check("v2: its video plays", J("document.getElementById('vid').dataset.src === window.__old && document.getElementById('vid').getAttribute('src') === window.__old"))
    check("v2: no sound switch, its own script", J("document.getElementById('versions').hidden") and J("document.querySelector('#script .sline .say').textContent") == "An older line")
    check("v2: only v2's notes, resolved too, with Claude's reply", J("[...document.querySelectorAll('#notes .note .body')].map((b) => b.textContent)") == ["Logo too small"]
          and pg.locator("#notes .note .reply").count() == 1 and pg.locator("#notes .note .acts").count() == 0 and pg.locator("#lane .mark").count() == 1)
    check("v2: read-only banner, no note form, no verdict", J("document.getElementById('pastTxt').textContent") == "Viewing v2, read-only"
          and pg.locator("#b-current").is_visible() and not pg.locator("#composer").is_visible() and not pg.locator("#verdict").is_visible()
          and not pg.locator("#script .lbtn").first.is_visible())
    check("v2: the address names the version", J("location.hash") == "#explainer@v2")
    J("document.activeElement.blur()"); pg.keyboard.press("n"); pg.keyboard.press("i"); pg.wait_for_timeout(100)
    check("v2: n and i start nothing", J("document.activeElement.id") != "noteText" and J("document.getElementById('tFrom').value") in ("", "0:00.0"))
    pg.locator("#lane").scroll_into_view_if_needed(); lb = pg.locator("#lane").bounding_box(); ly = lb["y"] + lb["height"] / 2
    pg.mouse.move(lb["x"] + lb["width"] * .4, ly); pg.mouse.down()
    for i in range(20): pg.mouse.move(lb["x"] + lb["width"] * (.4 + .4 * i / 19), ly)
    pg.mouse.up(); pg.wait_for_timeout(400)
    check("v2: the lane marks no range, it scrubs", pg.locator("#lane .sel").count() == 0
          and abs(J("document.getElementById('vid').currentTime / document.getElementById('vid').duration") - .8) < .03)
    pg.locator("#script .sline .w").first.click(); pg.wait_for_timeout(200)
    check("v2: tapping a word opens no note form", J("document.getElementById('composer').parentNode.id") == "dock" and J("document.getElementById('lineTarget').hidden"))
    pg.locator("#b-current").click(); pg.wait_for_timeout(500)
    check("Back to v3: current video, form and verdict back", J("document.getElementById('vid').dataset.src !== window.__old") and pg.locator("#composer").is_visible()
          and pg.locator("#verdict").is_visible() and J("document.getElementById('pastBar').hidden") and J("location.hash") == "#explainer")
    J("location.hash = '#explainer@v2'"); pg.wait_for_timeout(400)
    check("a #key@v2 link opens that version", J("document.getElementById('pastTxt').textContent") == "Viewing v2, read-only" and not J("document.getElementById('pastBar').hidden"))
    pg.locator(".cutbtn").filter(has_text="Teaser").first.click(); pg.wait_for_timeout(300)
    pg.locator(".cutbtn").filter(has_text="Explainer").first.click(); pg.wait_for_timeout(400)
    check("switching cut returns to the current version", J("document.getElementById('pastBar').hidden") and J("document.getElementById('verSel').value") == "3")
    # Claude's copy of the open note on the teaser links back to it
    J("""window.__db.doc('notes/new--teaser').set({ cut: 'teaser', t: null, tEnd: null, region: null, item: null, line: null, quote: null,
      qStart: null, qEnd: null, text: 'Music too loud', status: 'open', reply: '', by: 'claude', from: { cut: 'explainer', id: 'new' },
      version: 1, createdAt: '2026-11-03T10:00:00Z' })"""); pg.wait_for_timeout(300)
    pg.locator(".cutbtn").filter(has_text="Teaser").first.click(); pg.wait_for_timeout(400)
    copy = pg.locator("#notes .note").filter(has_text="Music too loud")
    check("a carried note says Claude and where it came from", copy.count() == 1 and "Claude" in copy.locator(".who").text_content()
          and copy.locator(".from").count() == 1 and copy.get_by_role("button", name="Edit").count() == 0)
    copy.locator(".from").click(); pg.wait_for_timeout(500)
    check("its link opens the original note", J("location.hash") == "#explainer" and pg.locator("#notes .note.focus").filter(has_text="Music too loud").count() == 1)
    pg.locator("#notes .note.focus").get_by_role("button", name="Resolve").click(); pg.wait_for_timeout(400)
    pg.locator("#approve").click(); pg.wait_for_timeout(300)
    check("resolved, then Approve writes it for v3", J("window.__store.verdicts.explainer.version") == 3 and J("window.__store.verdicts.explainer.state") == "approved"
          and J("document.querySelector('#approve').getAttribute('aria-pressed')") == "true" and J("document.getElementById('approveHint').hidden"))
    check("no page errors (versions)", not errs)
    if errs: print(errs)
    ctx.close()

    # compare: the explainer's v3 beside its kept v2 (the teaser's video), two notes written on v2
    ctx = b.new_context(viewport={"width": W, "height": H}); pg = ctx.new_page(); J = pg.evaluate
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "#explainer"); pg.wait_for_function("document.getElementById('vid').readyState >= 1", timeout=30000)
    J("""(async () => {
      const s = window.__store, x = s.cuts.explainer, t = s.cuts.teaser;
      window.__old = t.video;
      for (const [id, text] of [['o1', 'Logo too small'], ['o2', 'Too dark']]) await window.__db.doc('notes/' + id).set({ cut: 'explainer', t: 1,
        tEnd: null, region: null, item: null, line: null, quote: null, qStart: null, qEnd: null, text, status: 'resolved', reply: '', version: 2,
        by: 'u_reviewer', createdAt: '2026-11-02T10:00:00Z' });
      await window.__db.doc('cuts/explainer').set({ ...x, version: 3, changes: [{ v: 2, note: 'Bigger logo' }, { v: 3, note: 'Quieter music' }],
        history: [{ v: 2, video: t.video, poster: t.poster, script: [], length: 8, note: 'Bigger logo' }] });
    })()"""); pg.wait_for_timeout(600)
    V = "document.getElementById('vid')"; V2 = "document.getElementById('vid2')"
    check("no Compare on the current version", not pg.locator("#b-cmp").is_visible())
    cur = J(f"{V}.dataset.src")
    pg.select_option("#verSel", "2"); pg.wait_for_timeout(400)
    check("Compare offered on a kept past version", pg.locator("#b-cmp").is_visible())
    pg.locator("#b-cmp").click(); pg.wait_for_timeout(400)
    check("compare: two pictures, the current (alt kept) and v2's video", pg.locator("#vid").is_visible() and pg.locator("#vid2").is_visible()
          and J(f"{V}.dataset.src") == cur and J(f"{V2}.getAttribute('src') === window.__old"))
    check("compare: labelled v3 · current and v2 · its change", J("document.getElementById('cmpCur').textContent") == "v3 · current"
          and J("document.getElementById('cmpSel').selectedOptions[0].textContent") == "v2 · Bigger logo")
    check("compare: the address says so", J("location.hash") == "#explainer@v3~v2")
    pg.wait_for_function(f"{V2}.readyState >= 2 && {V}.readyState >= 2", timeout=30000)
    pg.locator("#b-play").click(); pg.wait_for_timeout(1000)
    check("play plays both", J(f"!{V}.paused && !{V2}.paused"))
    pg.locator("#b-play").click(); pg.wait_for_timeout(400)
    check(f"pause pauses both, together ({J(f'[{V}.currentTime, {V2}.currentTime]')})", J(f"{V}.paused && {V2}.paused && Math.abs({V}.currentTime - {V2}.currentTime) < 0.1"))
    pg.locator("#track").scroll_into_view_if_needed(); bb = pg.locator("#track").bounding_box()
    pg.mouse.click(bb["x"] + bb["width"] * .5, bb["y"] + bb["height"] / 2); pg.wait_for_timeout(600)
    t1, t2 = J(f"[{V}.currentTime, {V2}.currentTime]")
    check(f"a seek on the timeline moves both ({t1:.2f}, {t2:.2f})", 5 < t1 < 7 and abs(t1 - t2) < 0.1)
    y = bb["y"] + bb["height"] / 2; pg.mouse.move(bb["x"] + bb["width"] * .5, y); pg.mouse.down()
    for i in range(20): pg.mouse.move(bb["x"] + bb["width"] * (.5 - .3 * i / 19), y); pg.wait_for_timeout(15)
    pg.wait_for_timeout(400); m1, m2 = J(f"[{V}.currentTime, {V2}.currentTime]")
    pg.mouse.up(); pg.wait_for_timeout(600)
    t1, t2 = J(f"[{V}.currentTime, {V2}.currentTime]")
    check(f"a drag on the timeline moves both, while held ({m1:.2f}, {m2:.2f}) and after ({t1:.2f}, {t2:.2f})", abs(t1 / J(f"{V}.duration") - .2) < .03 and abs(t1 - t2) < 0.1 and abs(m1 - m2) < 0.1)
    J("document.activeElement.blur()")
    for _ in range(3): pg.keyboard.press("."); pg.wait_for_timeout(150)
    pg.locator("#b-back").click(); pg.wait_for_timeout(400)
    s1, s2 = J(f"[{V}.currentTime, {V2}.currentTime]")
    check(f"frame steps move both ({s1:.3f}, {s2:.3f})", abs(s1 - t1 - 2 / 30) < 0.02 and abs(s1 - s2) < 0.05)
    check("one speed button, at 1×", pg.locator("#b-rate").count() == 1 and J("document.getElementById('b-rate').textContent") == "1×")
    for r in (1.5, 2, 0.5, 1):   # each press steps to the next speed, then round again
        pg.locator("#b-rate").click(); pg.wait_for_timeout(100)
        check(f"the speed button steps to {r:g}× and both play at it", J(f"[{V}.playbackRate, {V2}.playbackRate]") == [r, r]
              and J("document.getElementById('b-rate').textContent") == f"{r:g}×")
    check("sound from the current version only", J(f"[{V}.muted, {V2}.muted]") == [False, True])
    pg.locator("#snd2").click(); pg.wait_for_timeout(100)
    check("the speaker moves the sound to v2", J(f"[{V}.muted, {V2}.muted]") == [True, False])
    pg.locator("#snd1").click(); pg.wait_for_timeout(100)
    check("and back", J(f"[{V}.muted, {V2}.muted]") == [False, True])
    pg.locator("#noteText").fill("Still loud here"); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["text"] == "Still loud here"]
    check("a note while comparing goes on the current version", len(n) == 1 and n[0]["version"] == 3 and n[0]["cut"] == "explainer"
          and pg.locator("#vid2").is_visible())
    if W <= 760:
        b1, b2 = pg.locator("#stage").bounding_box(), pg.locator("#stage2").bounding_box()
        check("phone: the pictures stack", b2["y"] >= b1["y"] + b1["height"] - 1 and abs(b1["x"] - b2["x"]) < 2)
    check("no horizontal scroll while comparing", J("document.documentElement.scrollWidth <= window.innerWidth"))
    check("the chip counts v2's notes", J("document.getElementById('cmpNotes').textContent") == "2 notes")
    pg.locator("#cmpNotes").click(); pg.wait_for_timeout(500)
    check("the chip opens v2 read-only and leaves compare", J("document.getElementById('pastTxt').textContent") == "Viewing v2, read-only"
          and not pg.locator("#vid2").is_visible() and J("location.hash") == "#explainer@v2" and pg.locator("#b-cmp").is_visible()
          and J(f"{V}.dataset.src === window.__old"))
    pg.locator("#b-cmp").click(); pg.wait_for_timeout(400)
    check("Compare from v2 compares it with the current version", pg.locator("#vid2").is_visible() and J("document.getElementById('cmpSel').value") == "2"
          and J("location.hash") == "#explainer@v3~v2")
    pg.locator("#b-cmp").click(); pg.wait_for_timeout(400)
    check("Compare again goes back to viewing v2", not pg.locator("#vid2").is_visible() and J("location.hash") == "#explainer@v2")
    pg.locator("#b-current").click(); pg.wait_for_timeout(400)
    J("location.hash = '#explainer@v3~v2'"); pg.wait_for_timeout(500)
    check("a #key@v3~v2 link opens compare", pg.locator("#vid2").is_visible() and J(f"{V2}.getAttribute('src') === window.__old"))
    pg.select_option("#verSel", "2"); pg.wait_for_timeout(400)
    check("the version menu leaves compare", not pg.locator("#vid2").is_visible() and J("document.getElementById('verSel').value") == "2")
    pg.locator("#b-cmp").click(); pg.wait_for_timeout(300)
    pg.locator(".cutbtn").filter(has_text="Teaser").first.click(); pg.wait_for_timeout(400)
    check("a cut switch leaves compare; no Compare without history", not pg.locator("#vid2").is_visible() and not J(f"{V2}.hasAttribute('src')")
          and not pg.locator("#b-cmp").is_visible() and not J(f"{V}.muted"))
    pg.locator(".cutbtn").filter(has_text="Carousel").first.click(); pg.wait_for_timeout(400)
    check("no Compare on a set", not pg.locator("#b-cmp").is_visible())
    # deep links: a key with @ in it, a version that isn't kept, a script that wasn't kept
    J("""(async () => { const t = window.__store.cuts.teaser; await window.__db.doc('cuts/teaser@v2').set({ ...t, title: 'Teaser at v2', order: 99 }); })()""")
    pg.wait_for_timeout(400); J("location.hash = '#teaser@v2'"); pg.wait_for_timeout(500)
    check("a key with @ in it opens that cut", J("document.getElementById('title').textContent") == "Teaser at v2" and J("location.hash") == "#teaser@v2")
    J("location.hash = '#explainer@v9'"); pg.wait_for_timeout(500)
    check("a link to a version that isn't kept shows the current one and fixes the address",
          J("location.hash") == "#explainer" and pg.locator("#pastBar").is_hidden())
    J("""(async () => { const x = window.__store.cuts.explainer; await window.__db.doc('cuts/explainer').set({ ...x,
      history: [{ v: 1, video: x.history[0].video, poster: x.history[0].poster, note: '' }, ...x.history] }); })()""")
    pg.wait_for_timeout(400); J("location.hash = '#explainer@v1'"); pg.wait_for_timeout(500)
    check("a past version that kept no script shows none", J("document.getElementById('pastTxt').textContent") == "Viewing v1, read-only"
          and pg.locator("#scriptCard").is_hidden())
    check("no page errors (compare)", not errs)
    if errs: print(errs)
    ctx.close(); b.close()

print(f"{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
