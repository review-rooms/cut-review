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
    # scrub a range
    pg.locator("#track").scroll_into_view_if_needed()
    bb = pg.locator("#track").bounding_box(); y = bb["y"] + bb["height"] / 2
    pg.mouse.move(bb["x"] + bb["width"] * .25, y); pg.mouse.down()
    for i in range(20): pg.mouse.move(bb["x"] + bb["width"] * (.25 + .25 * i / 19), y)
    pg.mouse.up(); pg.wait_for_timeout(400)
    fr, to = J("[document.getElementById('tFrom').value, document.getElementById('tTo').value]")
    check(f"scrub marks a range ({fr}–{to})", fr.startswith("0:02") and to.startswith("0:04") and pg.locator("#track .sel").count() == 1)
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
    pg.locator("#b-add").click(); pg.wait_for_timeout(600)
    n = [x for x in store("notes") if x["cut"] == "teaser"]
    check("note saved with range and region", len(n) == 1 and n[0]["t"] == 1.5 and n[0]["tEnd"] is not None and n[0]["region"] and n[0]["region"]["w"] > .2)
    check("note card and timeline mark shown", pg.locator("#notes .note").count() == 1 and pg.locator("#track .mark").count() == 1)
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
    # the verdict toggles: press the one that is on to go back to unreviewed
    pg.locator('#verdict [data-v="changes"]').click(); pg.wait_for_timeout(300)
    on = J("window.__store.verdicts.teaser && window.__store.verdicts.teaser.state")
    pg.locator('#verdict [data-v="changes"]').click(); pg.wait_for_timeout(300)
    check("verdict toggles on and back off", on == "changes" and J("window.__store.verdicts.teaser.state") == "none")
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
    ctx.close(); b.close()

print(f"{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
